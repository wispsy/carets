import asyncio
import importlib.util
from pathlib import Path
import random
import unittest

from carets import KeyMsg, WindowSizeMsg
from carets.input import AnsiInputParser
from carets.testing import TestProgram, assert_layout

spec = importlib.util.spec_from_file_location("tutorials", Path(__file__).resolve().parents[1] / "examples" / "tutorials.py")
tutorials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tutorials)


class FixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_counter_form_dashboard_and_multi_pane_without_terminal(self):
        async with TestProgram(tutorials.Counter()) as test:
            await test.send_bytes(b"++")
            test.assert_snapshot("Count: 2")
            test.assert_fits(20, 1)
        self.assertEqual(test.terminal.restore_count, 1)
        self.assertFalse(test.terminal.raw)
        async with TestProgram(tutorials.FormExample()) as test:
            await test.send(KeyMsg("3", "3"), KeyMsg("enter"))
            self.assertEqual(test.model.form.as_dict()["count"], 3)
        async with TestProgram(tutorials.Dashboard()) as test:
            identity = test.program.schedule(test.model.start())
            await test.settle()
            await test.advance(1)
            test.assert_snapshot("Completed ticks: 1")
            self.assertTrue(test.program.cancel(identity))
            await test.advance(1)
            test.assert_snapshot("Completed ticks: 1")
        async with TestProgram(tutorials.MultiPane()) as test:
            await test.resize(60, 4)
            assert_layout(test.model.focus.zones, 60, 4)
            await test.send_bytes(b"\t")
            self.assertEqual(test.model.focus.focused, "right")
            await test.send_bytes(b"\x1b[Z")
            self.assertEqual(test.model.focus.focused, "left")


class ParserPropertyTests(unittest.TestCase):
    def test_chunking_preserves_common_protocol_events(self):
        data = "héllo 🌍\x1b[A\x1b[<0;4;5M\x1b[200~paste\ntext\x1b[201~\x1b[Z".encode()
        baseline = AnsiInputParser()
        expected = baseline.feed(data) + baseline.finish()
        for seed in range(40):
            randomizer, parser, actual, offset = random.Random(seed), AnsiInputParser(), [], 0
            while offset < len(data):
                length = randomizer.randint(1, 7)
                actual.extend(parser.feed(data[offset:offset + length]))
                offset += length
            actual.extend(parser.finish())
            self.assertEqual(actual, expected, f"chunk seed={seed}")

    def test_seeded_arbitrary_byte_inputs_finish_without_crashing(self):
        for seed in range(40):
            randomizer = random.Random(seed)
            parser = AnsiInputParser()
            parser.feed(bytes(randomizer.randrange(256) for _ in range(128)))
            parser.finish()
