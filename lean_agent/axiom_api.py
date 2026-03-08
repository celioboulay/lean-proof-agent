"""
https://github.com/AxiomMath/axiom-lean-engine
https://axle.axiommath.ai/v1/docs/ Published on March 5 by Axiom
Will replace the local checker since it's super fast and API is open to everyone
"""

import asyncio
from typing import List
from pathlib import Path
from axle import AxleClient
from axle.types import CheckResponse

def read_lean(file):
    return Path(file).read_text()

# terrible name choice since it's also a axiom method ahah. will change
async def verify_proof(file="lean_agent/Work.lean"): # https://axle.axiommath.ai/v1/docs/tools/verify_proof/
    async with AxleClient() as client:
        result = await client.check(
            content=read_lean(file),
            environment="lean-4.28.0",
        )
        return result