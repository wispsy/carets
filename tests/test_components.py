from dataclasses import replace
import unittest

from carets import KeyMsg
from carets.components import (Component, ComponentState, ComponentAdapter, Button,
                               Checkbox, Label, Progress, TextInput, Spinner, ListModel, Viewport)


class ComponentTests(unittest.TestCase):
    def test_contracts_and_visible_accessible_states(self):
        state = ComponentState("save", "Save changes", focused=True)
        button = Button("Save", state)
        self.assertIsInstance(button, Component)
        self.assertEqual(button.update(KeyMsg("enter")).activations, 1)
        self.assertEqual(button.activations, 0)
        self.assertEqual(button.update(KeyMsg("enter", action="release")), button)
        for flag in ("disabled", "read_only"):
            blocked = replace(button, state=replace(state, **{flag: True}))
            self.assertEqual(blocked.update(KeyMsg("enter")), blocked)
            self.assertIn(flag.replace("_", " "), blocked.accessibility())
        check = Checkbox("Enable", state=state).update(KeyMsg("space"))
        self.assertTrue(check.checked)
        for control in (check, Label("界"), Progress(.5)):
            self.assertIsInstance(control, Component)
            self.assertGreater(control.measure().width, 0)
        self.assertIn("50%", Progress(.5).accessibility())

    def test_legacy_adapters_and_grapheme_editing(self):
        text = TextInput("Ae\u0301👩‍💻界", cursor=7)
        text = text.update(KeyMsg("end"))
        text = text.update(KeyMsg("backspace"))
        self.assertEqual(text.value, "Ae\u0301👩‍💻")
        text = text.update(KeyMsg("left")).update(KeyMsg("backspace"))
        self.assertEqual(text.value, "A👩‍💻")
        self.assertEqual(text.cursor, 1)
        self.assertEqual(text.update(KeyMsg("x", "x", modifiers=("ctrl",))), text)
        state = ComponentState("input", focused=False)
        adapter = ComponentAdapter(text, state)
        self.assertNotIn("|", adapter.view())
        self.assertEqual(adapter.update(KeyMsg("x", "x")), adapter)
        for model in (text, ListModel(["a", "b"]), Viewport("a\nb"), Spinner()):
            self.assertIsInstance(ComponentAdapter(model, state), Component)
        selected = ComponentAdapter(ListModel(["a", "b"]), replace(state, focused=True, read_only=True))
        self.assertEqual(selected.update(KeyMsg("down")).model.selected, 1)
        self.assertEqual(Spinner(frames=()).update(KeyMsg("tick")).view(), "")
