import asyncio
from typing import List
from pathlib import Path
from pprint import pprint
from axle import AxleClient
from axle.types import CheckResponse, Messages

def read_lean(file):
    return Path(file).read_text()


async def check_proof(file="lean_agent/Work.lean"):
    async with AxleClient() as client:
        result = await client.check( # verify proof may also be good
            content=read_lean(file),
            environment="lean-4.28.0",
        )
        # result.content is the original proof, and info/timings are not (yet?) useful here 
        if result.okay:
            print("all good")
        else:
            print("\n=== FAILED DECLARATIONS ===")
            pprint(result.failed_declarations)
            print("\n=== LEAN MESSAGES ===")
            pprint(result.lean_messages) # Messages class
            print("\n=== TOOL MESSAGES ===")
            pprint(result.tool_messages)

        return result


asyncio.run(check_proof())


class Agent: # will be used to fix subgoals, errors or prove required lemmas
    def __init__(self, Lean_file_):
        self.goal = None
        self.Lean_file = Lean_file_ # should be same as main proof, add access restrictions

    def commit_change(self):
        pass


class Proof: # contains all the data needed to guide the llm through the proof
    def __init__(self, NL_proof, Lean_file_, max_steps=5):
        self.NL_proof = NL_proof # hopefully properly parsed

        self.Lean_file = Lean_file_ # several files in case of // workflows
        self.Lean_proof = read_lean(self.Lean_file) # TODO create if doesnt exist

        self.max_steps = max_steps
        self.responses: List[str] = []

        self.agents: List[Agent] = [] 

    def formalize_statement(self):
        pass

    def solve(self):
        pass