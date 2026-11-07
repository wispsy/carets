"""Actual buffered stdin/TTY input worker for the parent process regression."""

import asyncio
import io
import sys

from carets import KeyMsg, Program, TerminalSession


class Session(TerminalSession):
    def start(self, program):
        super().start(program)
        print("READY", flush=True)


class Model:
    def update(self, message):
        if isinstance(message, KeyMsg):
            print("GOT:" + message.key, flush=True)
            self.program.stop()

    def view(self):
        return ""


def main():
    model = Model()
    model.program = Program(model, input_stream=sys.stdin.buffer, output_stream=io.StringIO(),
                            terminal=Session(sys.stdin.buffer, sys.stderr))
    asyncio.run(model.program.run())


if __name__ == "__main__":
    main()
