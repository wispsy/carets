import asyncio
from dataclasses import dataclass, replace
import sys
import termios
import tty
from typing import Callable, Coroutine, Optional, Tuple


# --- 1. Core Framework Types (tea.Msg, tea.Cmd, tea.Model) ---
class Msg: pass


@dataclass(frozen=True)
class KeyMsg(Msg):
    key: str


@dataclass(frozen=True)
class QuitMsg(Msg): pass


# A Cmd is an async function that returns a Msg
Cmd = Callable[[], Coroutine[None, None, Optional[Msg]]]


class Model:
    def init(self) -> Optional[Cmd]:
        return None

    def update(self, msg: Msg) -> Tuple["Model", Optional[Cmd]]:
        return self, None

    def view(self) -> str:
        return ""


# --- 2. The Runtime Program (tea.Program) ---
class Program:
    def __init__(self, initial_model: Model):
        self.model = initial_model
        self.queue: asyncio.Queue[Msg] = asyncio.Queue()
        self.last_lines: int = 0

    def render(self):
        output = self.model.view()
        # Move cursor up to overwrite previous frame cleanly (inline mode)
        if self.last_lines > 0:
            sys.stdout.write(f"\x1b[{self.last_lines}A")

        lines = output.split("\n")
        for line in lines:
            # \x1b[2K clears the current line, \r moves to column 0
            sys.stdout.write(f"\x1b[2K\r{line}\n")
        sys.stdout.flush()
        self.last_lines = len(lines)

    def _on_stdin(self):
        ch = sys.stdin.read(1)
        self.queue.put_nowait(KeyMsg(key=ch))

    async def _run_cmd(self, cmd: Cmd):
        msg = await cmd()
        if msg is not None:
            await self.queue.put(msg)

    async def run(self):
        loop = asyncio.get_running_loop()
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            # Put terminal in cbreak mode & hide cursor
            tty.setcbreak(fd)
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()

            loop.add_reader(fd, self._on_stdin)

            # Run Init() and initial View()
            if init_cmd := self.model.init():
                asyncio.create_task(self._run_cmd(init_cmd))
            self.render()

            # Main Elm Event Loop
            while True:
                msg = await self.queue.get()
                if isinstance(msg, QuitMsg):
                    break
                self.model, cmd = self.model.update(msg)
                if cmd:
                    asyncio.create_task(self._run_cmd(cmd))
                self.render()

        finally:
            loop.remove_reader(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            sys.stdout.write("\x1b[?25h")  # Restore cursor
            sys.stdout.flush()


# --- 3. Example App Using Our Engine ---
@dataclass(frozen=True)
class CounterModel(Model):
    count: int = 0
    status: str = "Ready"

    def update(self, msg: Msg) -> Tuple[Model, Optional[Cmd]]:
        if isinstance(msg, KeyMsg):
            if msg.key == "q":
                return self, lambda: asyncio.sleep(0, result=QuitMsg())
            elif msg.key == "k":
                return replace(self, count=self.count + 1), None
            elif msg.key == "j":
                return replace(self, count=self.count - 1), None
        return self, None

    def view(self) -> str:
        return (
            f"\x1b[1;35m╭──────────────────────────╮\x1b[0m\n"
            f"\x1b[1;35m│\x1b[0m  BubblePy Counter: \x1b[1;32m{self.count:<4}\x1b[0m  \x1b[1;35m│\x1b[0m\n"
            f"\x1b[1;35m╰──────────────────────────╯\x1b[0m\n"
            f"\x1b[2mPress 'k' (+), 'j' (-), or 'q' to quit.\x1b[0m"
        )


if __name__ == "__main__":
    asyncio.run(Program(CounterModel()).run())
