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

async def verify_proof(file="lean_agent/Work.lean"): # https://axle.axiommath.ai/v1/docs/tools/verify_proof/
    async with AxleClient() as client:
        result = await client.check(
            content=read_lean(file),
            environment="lean-4.28.0",
        )
        return result
    
class Verification: # contains all the data needed to guide the llm through the proof
    def __init__(self, NL_proof, Lean_file_, max_steps=5):
        # the proof the agent is attempting to translate and verifiy
        self.NL_proof = NL_proof # hopefully properly parsed

        self.Lean_file = Lean_file_ # several files in case of // workflows
        self.Lean_proof = read_lean(self.Lean_file) # TODO create if doesnt exist

        self.max_steps = max_steps
        self.responses: List[str] = []

    def update_proof(self):
        self.Lean_proof = read_lean(self.Lean_file)
    

    def process_feedback(self, result: CheckResponse):
        verified = result.okay

        if verified: # terminates this workflow
            self.responses.append("VERIFIED")
            return

        errors = result.lean_messages.errors
        warnings = result.lean_messages.warnings
        infos = result.lean_messages.infos
        compiler_feedback = []

        if errors:
            compiler_feedback.extend(errors)
        if warnings:
            compiler_feedback.extend(warnings)
        if infos:
            compiler_feedback.extend(infos)

        log = "\n".join(str(m) for m in compiler_feedback)
        self.responses.append(log)