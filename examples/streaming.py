"""Run with PYTHONPATH=src python examples/streaming.py; no terminal required."""
import asyncio
from dataclasses import dataclass

from carets import Command, CommandErrorMsg, Msg, Program


@dataclass(frozen=True)
class Text(Msg):
    value: str


class Done(Msg):
    pass


class Model:
    def __init__(self):
        self.text = ''
        self.program = None

    def update(self, message):
        if isinstance(message, Text):
            self.text += message.value
        elif isinstance(message, (Done, CommandErrorMsg)):
            self.program.stop()

    def view(self):
        return self.text


async def source():
    for value in ('Streaming ', 'through ', 'Carets.'):
        yield Text(value)
        await asyncio.sleep(0)
    yield Done()


async def main():
    model = Model()
    program = model.program = Program(model, stream_buffer=2)
    await program.run([], stop_on_eof=False, commands=[Command.stream(source)])
    print(model.view())


if __name__ == '__main__':
    asyncio.run(main())
