import subprocess
import json
from dataclasses import dataclass

@dataclass
class LeanResult:
    ok: bool
    output: str

def run_lean(project_root, lean_file):
    p = subprocess.run(
        ["lake", "env", "lean", "--json", lean_file],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    raw = (p.stdout or "") + (p.stderr or "")

    errors = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("severity") == "error":
            errors.append(msg)

    if errors:
        return LeanResult(False, json.dumps(errors, indent=2))

    return LeanResult(p.returncode == 0, raw)