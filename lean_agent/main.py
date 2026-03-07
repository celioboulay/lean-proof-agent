import asyncio
import json
from pathlib import Path

from lean_agent.api_client import chat_json, repair_json

BASE_DIR = Path(__file__).resolve().parent
LEAN_FILE = BASE_DIR / "Work.lean"

IMPORTS = "import Mathlib"

TEMPLATE = """{imports}
{helpers}
{theorem_statement}
{proof}
"""

SYSTEM = (BASE_DIR / "prompts" / "system.txt").read_text(encoding="utf-8")

FORBIDDEN_SUBSTRINGS = (
    "sorry",
    "admit",
    "axiom",
    "constant",
    "opaque",
    "unsafe",
    "set_option",
)

def write_file(imports: str, theorem_statement: str, proof: str, helpers: str):
    text = TEMPLATE.format(
        imports=imports.strip(),
        theorem_statement=theorem_statement.strip(),
        proof=proof.strip(),
        helpers=(helpers or "").strip(),
    )
    text = text.replace("\ufeff", "")
    LEAN_FILE.write_text(text, encoding="utf-8")

def _forbidden_error(text: str) -> str | None:
    low = (text or "").lower()
    for s in FORBIDDEN_SUBSTRINGS:
        if s in low:
            return f"Forbidden token found: {s}"
    return None

def _format_axle_output(res) -> str:
    msgs = []

    lean_messages = getattr(res, "lean_messages", None)
    if lean_messages is not None:
        errs = getattr(lean_messages, "errors", None) or []
        warns = getattr(lean_messages, "warnings", None) or []
        infos = getattr(lean_messages, "infos", None) or []
        msgs.extend(str(x) for x in errs)
        msgs.extend(str(x) for x in warns)
        msgs.extend(str(x) for x in infos)

    if not msgs:
        return "Lean check failed with no compiler output."

    return "\n".join(msgs)

def one_attempt(problem_text: str, last_error: str, history: list[dict]):
    user = {
        "problem_text": problem_text,
        "last_error": last_error,
        "previous_attempts": history[-3:],
    }

    try:
        obj = chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(user)},
            ],
            max_tokens=2500,
            temperature=0.1,
        )
    except Exception as e:
        return {
            "helpers": "",
            "theorem_statement": "",
            "proof": "",
            "_client_error": str(e),
        }

    if not isinstance(obj, dict):
        obj = repair_json(json.dumps(obj))

    for k in ("helpers", "theorem_statement", "proof"):
        if k not in obj or not isinstance(obj.get(k), str):
            obj = repair_json(json.dumps(obj))
            break

    return obj

def solve(problem_text: str, max_iters: int = 10):
    history = []
    last_error = ""

    from axiom_api import verify_proof
    from axle.types import CheckResponse

    for i in range(1, max_iters + 1):
        print(f"\nITER {i}")

        obj = one_attempt(problem_text, last_error, history)

        theorem_statement = (obj.get("theorem_statement") or "").strip()
        proof = (obj.get("proof") or "").strip()
        helpers = (obj.get("helpers") or "").strip()

        if not theorem_statement.startswith("theorem target") or not theorem_statement.endswith(":="):
            last_error = "Bad theorem_statement format. Must be: theorem target (...) : ... :="
            history.append(
                {
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (format)")
            continue

        if not proof.startswith("by"):
            last_error = "Bad proof format. Must start with: by"
            history.append(
                {
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (format)")
            continue

        if "import " in helpers:
            last_error = "helpers must not contain import lines"
            history.append(
                {
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (helpers)")
            continue

        fe = _forbidden_error("\n".join([IMPORTS, helpers, theorem_statement, proof]))
        if fe:
            last_error = fe
            history.append(
                {
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (forbidden)")
            continue

        write_file(IMPORTS, theorem_statement, proof, helpers)

        res: CheckResponse = asyncio.run(verify_proof(file=str(LEAN_FILE)))

        if res.okay:
            print("VERIFIED")
            print(f"Wrote: {LEAN_FILE}")
            return True

        last_error = _format_axle_output(res)
        history.append(
            {
                "helpers": helpers,
                "theorem_statement": theorem_statement,
                "proof": proof,
                "error": last_error,
            }
        )
        print("FAIL (lean)")

    return False

def main():
    print("Paste a math statement (plain text).\n")
    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)

    problem_text = "\n".join(lines).strip()
    if not problem_text:
        print("No input")
        return

    solve(problem_text, max_iters=5)

if __name__ == "__main__":
    main()