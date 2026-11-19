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
        if isinstance(message, CommandErrorMsg) or message.key == 'done':
            self.program.stop()

    def view(self):
        return ','.join(getattr(message, 'key', 'error') for message in self.messages)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    def make_program(self, **options):
        model = Model()
        program = Program(model, output_stream=io.StringIO(), **options)
        model.program = program
        return program

    async def test_lazy_incremental_ordered_delivery_before_exhaustion(self):
        program = self.make_program()
        consumed = asyncio.Event()
        closed = []
        original_update = program.model.update

        def update(message):
            original_update(message)
            if message.key == 'first':
                consumed.set()
        program.model.update = update

        async def source():
            try:
                yield KeyMsg('first')
                await consumed.wait()
                yield KeyMsg('second')
                yield KeyMsg('done')
            finally:
                closed.append(True)
        command = Command.stream(source)
        self.assertEqual(closed, [])
        await asyncio.wait_for(program.run([], stop_on_eof=False, commands=[command]), 1)
        self.assertEqual([m.key for m in program.model.messages], ['first', 'second', 'done'])
        self.assertEqual(closed, [True])

    async def test_bounded_lead_and_input_fairness(self):
        program = self.make_program(stream_buffer=2)
        entered, release = asyncio.Event(), asyncio.Event()
        produced = []
        original_update = program.model.update

        async def update(message):
            if message.key == '0':
                entered.set()
                await release.wait()
            original_update(message)
        program.model.update = update

        async def source():
            for index in range(1000):
                produced.append(index)
                yield KeyMsg(str(index))
        task = asyncio.create_task(program.run([], stop_on_eof=False, commands=[Command.stream(source)]))
        await entered.wait()
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertLessEqual(len(produced), 2)
        program.post(KeyMsg('done'))
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertLessEqual(len(program.model.messages), 3)

    async def test_explicit_cancel_and_shutdown_close_iterators(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                program = self.make_program()
                entered, closed = asyncio.Event(), []

                async def source():
                    try:
                        entered.set()
                        await asyncio.Event().wait()
                        yield KeyMsg('unreachable')
                    finally:
                        closed.append(True)
                task = asyncio.create_task(program.run([], stop_on_eof=False))
                await asyncio.sleep(0)
                identity = program.schedule(Command.stream(source))
                await entered.wait()
                if stop:
                    program.stop()
                else:
                    self.assertTrue(program.cancel(identity))
                    for _ in range(3):
                        await asyncio.sleep(0)
                    self.assertEqual(closed, [True])
                    program.stop()
                await asyncio.wait_for(task, 1)
                self.assertEqual(closed, [True])
                self.assertEqual(program.model.messages, [])

    async def test_bad_items_and_source_errors_are_command_errors(self):
        for mode in ('item', 'source', 'factory', 'close'):
            with self.subTest(mode=mode):
                program = self.make_program()
                closed = []
                class Source:
                    def __aiter__(self): return self
                    async def __anext__(self):
                        if mode == 'source':
                            raise RuntimeError('source failure')
                        if mode == 'close':
                            raise StopAsyncIteration
                        return 'not a message'
                    async def aclose(self):
                        closed.append(True)
                        if mode == 'close':
                            raise RuntimeError('close failure')
                def factory():
                    if mode == 'factory':
                        raise RuntimeError('factory failure')
                    return Source()
                await asyncio.wait_for(program.run([], stop_on_eof=False, commands=[Command.stream(factory)]), 1)
                self.assertIsInstance(program.model.messages[-1], CommandErrorMsg)
                self.assertEqual(closed, [] if mode == 'factory' else [True])

    async def test_empty_stream_and_async_factory(self):
        program = self.make_program()
        async def empty():
            if False:
                yield KeyMsg('unused')
        async def source():
            yield KeyMsg('done')
        async def factory():
            await asyncio.sleep(0)
            return source()
        await asyncio.wait_for(program.run([], stop_on_eof=False, commands=[Command.stream(empty), Command.stream(factory)]), 1)
        self.assertEqual([m.key for m in program.model.messages], ['done'])

    def test_configuration_is_explicit_and_bounded(self):
        for capacity in (True, 0, -1, 65537, 1.5):
            with self.assertRaises(ValueError):
                self.make_program(stream_buffer=capacity)
        with self.assertRaises(TypeError):
            Command.stream(None)
        with self.assertRaises(ValueError):
            Command(lambda: None, interval=1, streaming=True)
