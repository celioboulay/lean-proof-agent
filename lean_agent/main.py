import json
from pathlib import Path

from lean_runner import run_lean
from api_client import chat_json, repair_json

BASE_DIR = Path(__file__).resolve().parent

def _find_project_root(start: Path) -> Path:
    for p in [start] + list(start.parents):
        if (p / "lakefile.lean").exists() or (p / "lakefile.toml").exists():
            return p
    return start.parent

PROJECT_ROOT = _find_project_root(BASE_DIR)
LEAN_FILE = BASE_DIR / "Work.lean"

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


def _normalize_imports(imports: str) -> str:
    lines = [ln.strip() for ln in (imports or "").splitlines() if ln.strip()]
    lines = list(dict.fromkeys(lines))
    return "\n".join(lines)


def _imports_error(imports: str) -> str | None:
    lines = [ln.strip() for ln in (imports or "").splitlines() if ln.strip()]
    if "import Mathlib.Tactic" not in lines:
        return "imports must include: import Mathlib.Tactic"
    for ln in lines:
        if ln == "import Mathlib":
            return "imports must NOT include: import Mathlib"
        if not ln.startswith("import "):
            return "imports must contain only import lines"
    return None


def _forbidden_error(text: str) -> str | None:
    low = (text or "").lower()
    for s in FORBIDDEN_SUBSTRINGS:
        if s in low:
            return f"Forbidden token found: {s}"
    return None


def one_attempt(problem_text: str, last_error: str, history: list[dict]):
    user = {
        "problem_text": problem_text,
        "last_error": last_error,
        "previous_attempts": history[-3:], # feed the models it's previous mistakes
    }

    try:
        obj = chat_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(user)},
            ],
            max_tokens=2500,
            temperature=0.1, # by default, didn't try other values
        )
    except Exception as e:
        return {
            "imports": "import Mathlib.Tactic",
            "helpers": "",
            "theorem_statement": "",
            "proof": "",
            "_client_error": str(e),
        }

    if not isinstance(obj, dict):
        obj = repair_json(json.dumps(obj))

    for k in ("imports", "helpers", "theorem_statement", "proof"):
        if k not in obj or not isinstance(obj.get(k), str):
            obj = repair_json(json.dumps(obj))
            break

    return obj


def solve(problem_text: str, max_iters: int = 10):
    history = []
    last_error = ""

    for i in range(1, max_iters + 1):
        print(f"\nITER {i}")

        obj = one_attempt(problem_text, last_error, history)

        theorem_statement = (obj.get("theorem_statement") or "").strip()
        proof = (obj.get("proof") or "").strip()
        helpers = obj.get("helpers") or ""
        imports = _normalize_imports(obj.get("imports") or "")

        # First do a sanity check of the proposed proof
        if not theorem_statement.startswith("theorem target") or not theorem_statement.endswith(":="):
            last_error = "Bad theorem_statement format. Must be: theorem target (...) : ... :="
            history.append(
                {
                    "imports": imports,
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
                    "imports": imports,
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (format)")
            continue

        ie = _imports_error(imports)
        if ie:
            last_error = ie
            history.append(
                {
                    "imports": imports,
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (imports)")
            continue

        if "import " in helpers:
            last_error = "helpers must not contain import lines"
            history.append(
                {
                    "imports": imports,
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (helpers)")
            continue

        # we don't want to use forbidden tactics such as sorry
        fe = _forbidden_error("\n".join([imports, helpers, theorem_statement, proof]))
        if fe:
            last_error = fe
            history.append(
                {
                    "imports": imports,
                    "helpers": helpers,
                    "theorem_statement": theorem_statement,
                    "proof": proof,
                    "error": last_error,
                }
            )
            print("FAIL (forbidden)")
            continue
        
        # The proof is in the correct format -> we can sumbit it
        write_file(imports, theorem_statement, proof, helpers)
        res = run_lean(str(PROJECT_ROOT), str(LEAN_FILE))
        print(res.output[-1200:])

        history.append(
            {
                "imports": imports,
                "helpers": helpers,
                "theorem_statement": theorem_statement,
                "proof": proof,
                "error": res.output,
            }
        )

        if res.ok:
            print("VERIFIED")
            print(f"Wrote: {LEAN_FILE}")
            return True

        if len(res.output) <= 4000:
            last_error = res.output
        else:
            last_error = res.output[:2000] + "\n...\n" + res.output[-2000:]

    print("FAILED")
    return False


def main():
    print("Paste a math statement/exercise in plain text. End with an empty line.\n")
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

    solve(problem_text, max_iters=10)


if __name__ == "__main__":
    main()