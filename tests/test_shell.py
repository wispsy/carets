import importlib.util
from pathlib import Path
import unittest

from carets import AppShell, FocusManager, KeyMsg, ShellCommand, Theme, Style
from carets.testing import TestProgram
from carets.unicode import visual_width


class ShellTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_applications_share_resize_and_shell(self):
        root = Path(__file__).resolve().parents[1]/"examples"
        for name, model_name in (("gallery", "Gallery"), ("queue", "QueueApplication")):
            spec = importlib.util.spec_from_file_location(name, root/(name+".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            async with TestProgram(getattr(module, model_name)()) as app:
                await app.resize(18, 6)
                await app.send(KeyMsg("down"), KeyMsg("tab"))
                app.assert_fits(18, 6)
                await app.resize(90, 24)
                app.assert_fits(90, 24)
            self.assertEqual(app.terminal.restore_count, 1)

    async def test_unicode_modal_clipping_textual_status_and_focus(self):
        shell = AppShell("界👩‍💻", theme=Theme(error=Style(foreground="#ff0000")))
        for width, height in ((0, 0), (1, 1), (12, 4), (80, 24)):
            frame = shell.frame(width, height, body="界"*100, navigation=("Jobs", "Errors"), selected=1,
                modal="Confirm?\n[Cancel] [Accept]", status="failed", severity="error",
                commands=(ShellCommand("run", "r", "run", False),))
            lines = frame.buffer.to_text().splitlines()
            self.assertLessEqual(len(lines), height)
            self.assertTrue(all(visual_width(line) <= width for line in lines))
        frame = shell.frame(30, 4, status="failed", commands=(ShellCommand("run", "r", "run", False),))
        self.assertIn("failed | r run [disabled]", frame.buffer.to_text())
        focus = FocusManager()
        focus.register("body")
        focus.add_scope("dialog")
        focus.register("cancel", scope="dialog")
        focus.register("accept", scope="dialog")
        focus.activate("dialog", modal=True)
        for _ in range(5):
            focus.route(KeyMsg("tab"))
            self.assertIn(focus.focused, ("cancel", "accept"))
        focus.dismiss()
        self.assertEqual(focus.focused, "body")
