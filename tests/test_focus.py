import unittest

from carets import FocusManager, KeyMsg, MouseMsg, ZoneManager


class FocusTests(unittest.TestCase):
    def test_navigation_modal_trap_and_restoration(self):
        zones = ZoneManager()
        focus = FocusManager(zones)
        for index, name in enumerate(("a", "b", "c")):
            zones.define(name, index * 4, 0, 3, 1)
            focus.register(name)
        self.assertEqual(focus.navigate("right"), "b")
        focus.set_state("c", disabled=True)
        focus.route(KeyMsg("tab"))
        self.assertEqual(focus.focused, "a")
        focus.add_scope("dialog")
        focus.register("confirm", scope="dialog")
        focus.activate("dialog", modal=True)
        for _ in range(3): focus.route(KeyMsg("tab"))
        self.assertEqual(focus.focused, "confirm")
        with self.assertRaises(ValueError): focus.focus("a")
        with self.assertRaises(ValueError): focus.activate("root")
        focus.route(MouseMsg(0, 0))
        self.assertEqual(focus.focused, "confirm")
        focus.dismiss()
        self.assertEqual(focus.focused, "a")
        self.assertEqual(focus.indicator("a"), ">")

    def test_capture_target_bubble_and_stop(self):
        focus, calls = FocusManager(), []
        focus.register("parent")
        focus.register("child", parent="parent")
        focus.focus("child")
        for id, phase in (("parent", "capture"), ("child", "target"), ("parent", "bubble")):
            focus.on(id, phase, lambda event: calls.append((event.current, event.phase)))
        focus.route(KeyMsg("x", "x"))
        self.assertEqual(calls, [("parent", "capture"), ("child", "target"), ("parent", "bubble")])
        calls.clear()
        focus.on("child", "target", lambda event: event.stop())
        focus.route(KeyMsg("x", "x"))
        self.assertEqual(calls, [("parent", "capture"), ("child", "target")])

    def test_mouse_zones_disabled_and_read_only(self):
        zones, calls = ZoneManager(), []
        focus = FocusManager(zones)
        for name, x in (("a", 0), ("b", 5)):
            focus.register(name)
            zones.define(name, x, 0, 4, 2)
            focus.on(name, "target", lambda event: calls.append(event.target))
        focus.route(MouseMsg(6, 1))
        self.assertEqual((focus.focused, calls), ("b", ["b"]))
        focus.set_state("b", read_only=True)
        focus.route(KeyMsg("edit", "edit"))
        self.assertEqual(calls, ["b"])
        focus.set_state("b", disabled=True)
        focus.route(MouseMsg(6, 1))
        self.assertEqual(focus.focused, "a")

    def test_layout_overlap_priority_and_read_only_component_navigation(self):
        from dataclasses import replace
        from carets import Stack, Leaf
        from carets.components import ComponentAdapter, ComponentState, ListModel
        layout = Stack('root', Leaf('back'), Leaf('front')).arrange(20, 5)
        focus, calls = FocusManager(layout.zones()), []
        focus.register('back')
        focus.register('front')
        focus.on('back', 'target', lambda event: calls.append('back'))
        focus.on('front', 'target', lambda event: calls.append('front'))
        focus.route(MouseMsg(3, 2))
        self.assertEqual((layout.hit(3, 2), layout.zones().hit(3, 2).name, focus.focused), ('front',)*3)
        self.assertEqual(calls, ['front'])
        focus.set_state('front', disabled=True)
        focus.route(MouseMsg(3, 2))
        self.assertEqual(calls, ['front'])
        focus.set_state('front', disabled=False, read_only=True)
        focus.focus('front')
        model = ComponentAdapter(ListModel(('a', 'b')), ComponentState('front', focused=True, read_only=True))
        def update(event):
            nonlocal model
            model = model.update(event.message)
        focus.on('front', 'target', update)
        focus.route(KeyMsg('down'))
        self.assertEqual(model.model.selected, 1)
        count = len(calls)
        focus.route(KeyMsg('x', 'x'))
        focus.route(KeyMsg('enter'))
        self.assertEqual(len(calls), count)
