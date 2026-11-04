# Minimal carets example application.

import asyncio

from carets import Program
from carets.components import TextInput


async def main() -> None:
    await Program(TextInput(placeholder="Type here")).run()


if __name__ == "__main__":
    asyncio.run(main())

