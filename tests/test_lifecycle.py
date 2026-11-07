import asyncio
import io
import unittest

from carets import Command, CommandErrorMsg, KeyMsg, Program


class Model:
    def __init__(self):
        self.messages = []
        self.program = None

    def update(self, message):
        self.messages.append(message)
        if isinstance(message, CommandErrorMsg) or getattr(message, "key", None) == "done":
            self.program.stop()

    def view(self):
        return str(len(self.messages))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def program(self, **options):
        model = Model()
        program = Program(model, output_stream=io.StringIO(), **options)
        model.program = program
        return program

    async def test_sync_async_order_delay_and_ticks(self):
        sleeps = []
        count = 0
        async def sleep(seconds):
            sleeps.append(seconds)
            await asyncio.sleep(0)
        def tick():
            nonlocal count
            count += 1
            return KeyMsg("done" if count == 3 else "tick")
        program = self.program(sleep=sleep)
        await asyncio.wait_for(program.run([], stop_on_eof=False, commands=[Command.every(5, tick)]), 1)
        self.assertEqual([message.key for message in program.model.messages], ["tick", "tick", "done"])
        self.assertTrue(all(seconds == 5 for seconds in sleeps))

        async def asynchronous():
            await asyncio.sleep(0)
            return KeyMsg("done")
        program = self.program(sleep=sleep)
        await asyncio.wait_for(program.run([KeyMsg("input")], stop_on_eof=False, commands=[Command(asynchronous, delay=2)]), 1)
        self.assertEqual([message.key for message in program.model.messages], ["input", "done"])

    async def test_cancelled_producer_does_not_deliver_and_shutdown_wakes_input(self):
        entered, released = asyncio.Event(), []
        async def blocked():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.append("cancelled")
        program = self.program()
        runner = asyncio.create_task(program.run([], stop_on_eof=False))
        await asyncio.sleep(0)
        identity = program.schedule(Command(blocked))
        await entered.wait()
        self.assertTrue(program.cancel(identity))
        program.stop()
        await asyncio.wait_for(runner, 1)
        self.assertEqual(released, ["cancelled"])
        self.assertEqual(program.model.messages, [])

    async def test_background_failure_becomes_explicit_message(self):
        def fail():
            raise RuntimeError("producer failure")
        program = self.program()
        await asyncio.wait_for(program.run([], stop_on_eof=False, commands=[Command(fail)]), 1)
        self.assertIsInstance(program.model.messages[0], CommandErrorMsg)
        self.assertIsInstance(program.model.messages[0].error, RuntimeError)

    async def test_resources_restore_once_on_failure_and_cancellation(self):
        for mode in ("failure", "cancel"):
            calls = []
            program = self.program()
            program.add_cleanup(lambda: calls.append("first"))
            async def cleanup():
                calls.append("second")
            program.add_cleanup(cleanup)
            if mode == "failure":
                def fail(message):
                    raise RuntimeError("update failure")
                program.model.update = fail
                with self.assertRaisesRegex(RuntimeError, "update failure"):
                    await program.run([KeyMsg("x")])
            else:
                runner = asyncio.create_task(program.run([], stop_on_eof=False))
                await asyncio.sleep(0)
                runner.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await runner
            self.assertEqual(calls, ["second", "first"])
            with self.assertRaises(RuntimeError):
                await program.run([])
            self.assertEqual(calls, ["second", "first"])

    async def test_cleanup_failure_does_not_skip_other_resources(self):
        calls = []
        program = self.program()
        program.add_cleanup(lambda: calls.append("restored"))
        def fail():
            raise RuntimeError("cleanup")
        program.add_cleanup(fail)
        with self.assertRaisesRegex(RuntimeError, "cleanup"):
            await program.run([])
        self.assertEqual(calls, ["restored"])
