# Dependency-free unittest coverage for the carets public APIs.

import asyncio
import io
import unittest

from carets.components import ListModel, Spinner, TextInput, Viewport
from carets.huh import ConfirmField, Form, Group, InputField, SelectField
from carets.input import AnsiInputParser
from carets.renderer import CellDiffRenderer
from carets.runtime import KeyMsg, Program, WindowSizeMsg, batch
from carets.style import Border, Style, truncate_ansi, visual_width
from carets.zone import ZoneManager


class CaretsTests(unittest.TestCase):
    def test_batch_and_program(self):
        class Model:
            def __init__(self):
                self.messages = []

            def update(self, msg):
                self.messages.append(msg)

            def view(self):
                return "ok"

        model = Model()
        asyncio.run(Program(model, output_stream=io.StringIO()).run([batch(KeyMsg("a"), WindowSizeMsg(2, 1))]))
        self.assertEqual(len(model.messages), 2)

    def test_parser(self):
        parser = AnsiInputParser()
        self.assertEqual(parser.feed(b"a\x1b[A"), [KeyMsg("a", "a"), KeyMsg("up")])
        self.assertEqual(parser.feed(b"\x1b[<0;4;5M")[0].x, 3)
        self.assertEqual(parser.feed("\x1b[200~hello\nworld\x1b[201~")[0].key, "paste")

    def test_renderer_and_style(self):
        renderer = CellDiffRenderer(5, 1)
        output = renderer.render("hello")
        self.assertIn("\x1b[?2026h", output)
        self.assertEqual(visual_width("é"), 1)
        self.assertEqual(truncate_ansi("abcdef", 4), "abc…")
        self.assertIn("┌", Style(border=Border()).render("x"))

    def test_zones(self):
        manager = ZoneManager()
        zone = manager.define("main", 1, 2, 3, 4)
        self.assertTrue(zone.contains(2, 3))
        self.assertEqual(manager.hit(3, 5).name, "main")

    def test_components(self):
        input_model = TextInput().update(KeyMsg("a", "a"))
        self.assertEqual(input_model.value, "a")
        self.assertEqual(Viewport("a\nb\nc", height=2).update(KeyMsg("down")).offset, 1)
        self.assertEqual(ListModel(["a", "b"]).update(KeyMsg("down")).selected_item, "b")
        self.assertNotEqual(Spinner().update(KeyMsg("tick")).view(), Spinner().view())

    def test_form_validation(self):
        form = Form(
            [
                Group(
                    [
                        InputField("name", "Name", validators=(lambda value: "required" if not value else None,)),
                        SelectField("kind", "Kind", ["one", "two"], "bad"),
                        ConfirmField("agree", "Agree"),
                    ]
                )
            ]
        )
        self.assertFalse(form.validate())
        self.assertIn("name", form.errors)
        self.assertIn("kind", form.errors)


if __name__ == "__main__":
    unittest.main()

