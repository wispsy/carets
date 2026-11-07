"""Explicit, single-owner terminal setup with conservative platform fallbacks."""

from dataclasses import dataclass
import os
import signal
from threading import Lock, current_thread, main_thread

_ownership = Lock()


@dataclass(frozen=True)
class TerminalOptions:
    raw: bool = True
    alternate_screen: bool = False
    hide_cursor: bool = True
    mouse: bool = False
    bracketed_paste: bool = False
    signals: bool = True

    def __post_init__(self):
        if any(type(getattr(self, name)) is not bool for name in self.__dataclass_fields__):
            raise TypeError("Terminal options must be booleans")


@dataclass(frozen=True)
class TerminalCapabilities:
    tty: bool = False
    raw: bool = False
    resize: bool = False
    ansi: bool = False
    signals: bool = False


class SystemTerminal:
    """OS adapter; construction inspects streams without changing terminal state."""

    def __init__(self, input_stream, output_stream):
        self.input_stream, self.output_stream = input_stream, output_stream
        tty = bool(getattr(input_stream, "isatty", lambda: False)() and getattr(output_stream, "isatty", lambda: False)())
        posix = os.name == "posix"
        signals = tty and current_thread() is main_thread()
        self.capabilities = TerminalCapabilities(tty, tty and posix, signals and hasattr(signal, "SIGWINCH"),
                                                  tty and posix and os.environ.get("TERM") != "dumb", signals)

    def size(self):
        try:
            size = os.get_terminal_size(self.output_stream.fileno())
            return size.columns, size.lines
        except (AttributeError, OSError, ValueError):
            return 80, 24

    def capture_raw(self):
        import termios
        return termios.tcgetattr(self.input_stream.fileno())

    def enter_raw(self):
        import tty
        tty.setraw(self.input_stream.fileno())

    def restore_raw(self, state):
        import termios
        termios.tcsetattr(self.input_stream.fileno(), termios.TCSANOW, state)

    def install_signal(self, name, callback):
        selected = {"resize": "SIGWINCH", "interrupt": "SIGINT", "terminate": "SIGTERM"}[name]
        number = getattr(signal, selected)
        previous = signal.getsignal(number)
        signal.signal(number, lambda _number, _frame: callback())
        return number, previous

    def restore_signal(self, token):
        signal.signal(*token)


class TerminalSession:
    """A Program-owned resource. No raw mode or handlers exist before start()."""

    def __init__(self, input_stream, output_stream, *, options=None, backend=None):
        self.output_stream = output_stream
        self.options = options if options is not None else TerminalOptions()
        self.backend = backend if backend is not None else SystemTerminal(input_stream, output_stream)
        self.capabilities = self.backend.capabilities
        self._raw = None
        self._signals = []
        self._undo = []
        self._owned = False
        self._used = False

    def start(self, program):
        if self._used or not _ownership.acquire(blocking=False):
            raise RuntimeError("Terminal sessions require exclusive ownership and run once")
        self._owned = self._used = True
        program.add_cleanup(self.close)
        if self.options.raw and self.capabilities.raw:
            self._raw = self.backend.capture_raw()
            self.backend.enter_raw()
        if self.capabilities.ansi:
            for enabled, enter, leave in (
                (self.options.alternate_screen, "\x1b[?1049h", "\x1b[?1049l"),
                (self.options.hide_cursor, "\x1b[?25l", "\x1b[?25h"),
                (self.options.mouse, "\x1b[?1000h\x1b[?1006h", "\x1b[?1006l\x1b[?1000l"),
                (self.options.bracketed_paste, "\x1b[?2004h", "\x1b[?2004l"),
            ):
                if enabled:
                    self._undo.append(leave)
                    self.output_stream.write(enter)
            self.output_stream.flush()
        from .runtime import WindowSizeMsg
        def resize():
            program.post(WindowSizeMsg(*self.backend.size()))
        resize()
        if self.options.signals and self.capabilities.signals:
            if self.capabilities.resize:
                self._signals.append(self.backend.install_signal("resize", resize))
            for name in ("interrupt", "terminate"):
                self._signals.append(self.backend.install_signal(name, program.stop))

    def close(self):
        if not self._owned:
            return
        errors = []
        actions = [lambda token=token: self.backend.restore_signal(token) for token in reversed(self._signals)]
        actions += [lambda text=text: self.output_stream.write(text) for text in reversed(self._undo)]
        actions.append(self.output_stream.flush)
        if self._raw is not None:
            actions.append(lambda: self.backend.restore_raw(self._raw))
        try:
            for action in actions:
                try:
                    action()
                except BaseException as error:
                    errors.append(error)
        finally:
            self._owned = False
            _ownership.release()
        if errors:
            raise errors[0]
