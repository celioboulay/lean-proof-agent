# Published on March 5 by Axiom
# Will replace the local checker since it's super fast and API is open to everyone

import asyncio
from pathlib import Path
from axle import AxleClient

def parse_lean(file):
    return Path(file).read_text()

async def main():
    file = "lean_agent/Work.lean"
    async with AxleClient() as client:
        result = await client.check(
            content = parse_lean(file),
            environment="lean-4.28.0",
        )
        print(f"Valid: {result.okay}")
        if result.lean_messages.errors:
            print("Errors:", result.lean_messages.errors)

asyncio.run(main())