import os
import sys
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX pseudo-terminal coverage")
class PosixTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_attributes_restore_on_a_real_pseudo_terminal(self):
        import fcntl
        import pty
        import struct
        import termios
        from carets import Program, TerminalOptions, TerminalSession, WindowSizeMsg

        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        original = termios.tcgetattr(slave)
        messages = []
        class Model:
            def update(self, message): messages.append(message)
            def view(self): return ""
        with os.fdopen(os.dup(slave), "rb", buffering=0) as input_stream, os.fdopen(os.dup(slave), "w") as output_stream:
            session = TerminalSession(input_stream, output_stream, options=TerminalOptions(signals=False))
            await Program(Model(), terminal=session).run([])
        restored = termios.tcgetattr(slave)
        if sys.platform == "darwin":
            # Darwin sets PENDIN while restoring canonical input; it is kernel state.
            # https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/tty.c
            restored[3] &= ~termios.PENDIN
            original[3] &= ~termios.PENDIN
        self.assertEqual(restored, original)
        self.assertIn(WindowSizeMsg(80, 24), messages)
