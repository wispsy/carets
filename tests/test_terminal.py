import asyncio
import io
import unittest

from carets import KeyMsg, Program, TerminalCapabilities, TerminalOptions, TerminalSession, WindowSizeMsg


class Backend:
    def __init__(self, capabilities=None):
        self.capabilities = capabilities or TerminalCapabilities(True, True, True, True, True)
        self.dimensions = (80, 24)
        self.handlers = {}
        self.restored = []
        self.raw = False

    def size(self): return self.dimensions
    def capture_raw(self): return "original"
    def enter_raw(self): self.raw = True
    def restore_raw(self, state):
        self.raw = False
        self.restored.append(state)
    def install_signal(self, name, callback):
        self.handlers[name] = callback
        return name
    def restore_signal(self, name):
        self.handlers.pop(name)
        self.restored.append(name)


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_resize_signal_and_exactly_once_teardown(self):
        backend, output, messages = Backend(), io.StringIO(), []
        session = TerminalSession(io.BytesIO(), output, backend=backend,
            options=TerminalOptions(alternate_screen=True, mouse=True, bracketed_paste=True))
        class Model:
            def update(self, message): messages.append(message)
            def view(self): return ""
        program = Program(Model(), terminal=session)
        runner = asyncio.create_task(program.run([], stop_on_eof=False))
        await asyncio.sleep(0)
        self.assertTrue(backend.raw)
        backend.dimensions = (100, 40)
        backend.handlers["resize"]()
        await asyncio.sleep(0)
        backend.handlers["interrupt"]()
        await asyncio.wait_for(runner, 1)
        self.assertIn(WindowSizeMsg(100, 40), messages)
        self.assertFalse(backend.raw)
        self.assertEqual(backend.handlers, {})
        session.close()
        self.assertEqual(backend.restored.count("original"), 1)
        for sequence in ("\x1b[?1049l", "\x1b[?25h", "\x1b[?1000l", "\x1b[?2004l"):
            self.assertIn(sequence, output.getvalue())

    async def test_update_error_and_partial_setup_restore_raw(self):
        for partial in (False, True):
            backend = Backend()
            if partial:
                def fail():
                    backend.raw = True
                    raise OSError("setup")
                backend.enter_raw = fail
            session = TerminalSession(io.BytesIO(), io.StringIO(), backend=backend)
            class Model:
                def update(self, message): raise RuntimeError("update")
                def view(self): return ""
            with self.assertRaises((RuntimeError, OSError)):
                await Program(Model(), terminal=session).run([KeyMsg("x")])
            self.assertFalse(backend.raw)
            self.assertEqual(backend.restored.count("original"), 1)

    async def test_conservative_non_tty_and_independent_options(self):
        backend = Backend(TerminalCapabilities())
        output = io.StringIO()
        class Model:
            def update(self, message): pass
            def view(self): return ""
        await Program(Model(), terminal=TerminalSession(io.BytesIO(), output, backend=backend)).run([])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(backend.restored, [])

    async def test_owned_input_closes_before_terminal_restores(self):
        calls = []
        backend = Backend()
        original_restore = backend.restore_raw
        def restore(state):
            calls.append("terminal")
            original_restore(state)
        backend.restore_raw = restore
        class Source:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
            def close(self): calls.append("input")
        class Model:
            def update(self, message): pass
            def view(self): return ""
        await Program(Model(), terminal=TerminalSession(io.BytesIO(), io.StringIO(), backend=backend)).run(Source())
        self.assertEqual(calls, ["input", "terminal"])
        backend = Backend()
        options = TerminalOptions(raw=False, hide_cursor=False, signals=False)
        await Program(Model(), terminal=TerminalSession(io.BytesIO(), io.StringIO(), options=options, backend=backend)).run([])
        self.assertFalse(backend.raw)
        self.assertEqual(backend.restored, [])
