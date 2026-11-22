import random
import unittest
from carets.layout import (Column, Constraints, Insets, Leaf, Overlay, Rect, Row, Size,
                           Split, content, fixed, percent, weighted)


class LayoutTests(unittest.TestCase):
    def test_nested_measure_resize_and_stable_zones(self):
        sidebar = Leaf("nav", width=fixed(10), intrinsic=Size(4, 2))
        body = Column("body", Leaf("title", height=content(), intrinsic=Size(5, 1)), Leaf("output"), gap=1)
        tree = Row("shell", sidebar, body, gap=2, padding=Insets(1, 1, 1, 1))
        self.assertEqual(tree.measure(), Size(19, 4))
        first = tree.arrange(40, 10)
        self.assertEqual(first.get("body").bounds, Rect(13, 1, 26, 8))
        self.assertEqual(first.get("output").bounds, Rect(13, 3, 26, 6))
        self.assertEqual(first, tree.arrange(40, 10))
        smaller = tree.arrange(30, 8)
        self.assertEqual(smaller.get("output").bounds, Rect(13, 3, 16, 4))
        self.assertEqual(smaller.zones().hit(14, 4).name, "output")

    def test_percent_weights_caps_content_and_alignment(self):
        tree = Row("row", Leaf("quarter", width=percent(25)), Leaf("small", constraints=Constraints(maximum_width=2)),
                   Leaf("large", width=weighted(3)))
        result = tree.arrange(20, 2)
        self.assertEqual([result.get(n).bounds.width for n in ("quarter", "small", "large")], [5, 2, 13])
        centered = Column("c", Leaf("text", width=content(), height=content(), intrinsic=Size(3, 1)), align="center", justify="end")
        self.assertEqual(centered.arrange(9, 5).get("text").bounds, Rect(3, 4, 3, 1))

    def test_shortage_overlay_and_zero_rectangles(self):
        tree = Split("split", Leaf("a", constraints=Constraints(Size(8, 2))), Leaf("b", width=fixed(8)))
        result = tree.arrange(5, 1)
        self.assertTrue(result.overflow)
        self.assertEqual(result.get("a").clip, Rect(0, 0, 5, 1))
        self.assertEqual(result.get("b").clip.width, 0)
        overlay = Overlay("root", Leaf("back"), Leaf("front", width=fixed(2), height=fixed(1)))
        self.assertEqual(overlay.arrange(5, 2).hit(0, 0), "front")
        self.assertEqual(overlay.arrange(0, 0).get("front").clip.width, 0)

    def test_allocation_fills_without_rounding_overflow(self):
        rng = random.Random(17)
        for _ in range(100):
            count, width = rng.randint(1, 12), rng.randint(0, 100)
            row = Row("r", *(Leaf(str(i), width=weighted(rng.randint(1, 9))) for i in range(count)))
            result = row.arrange(width, 2)
            self.assertEqual(sum(p.bounds.width for p in result.placements[1:]), width)
            self.assertFalse(result.overflow)

    def test_invalid_tree_and_geometry_refused(self):
        with self.assertRaises(ValueError): Row("r", Leaf("same"), Leaf("same")).arrange(3, 3)
        with self.assertRaises(ValueError): percent(101)
        with self.assertRaises(ValueError): Constraints(Size(4, 0), maximum_width=3)
