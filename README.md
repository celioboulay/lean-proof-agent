## Lean Verification Agent

*2nd place - Mistral AI Hackathon (NYC)*

Latex-to-Lean4 automatic formalization and verification of mathematical proofs.

Given a .tex file, the system extracts theorem/proof blocks, generates Lean4 code via an LLM backend (API or self-hosted), compiles it locally, and reports whether it type-checks. Correctness is decided solely by the Lean4 trusted kernel.

![schema](data/schema.svg)

---

### Setup

- Python 3.10+
- Lean 4
- Unix system recommanded

Lean installation [(elan)](https://github.com/leanprover/elan)
```
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
elan toolchain install leanprover/lean4:stable
elan default leanprover/lean4:stable
```

Python environment:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```
export MISTRAL_API_KEY=your_key
```

To use another model, adapt api_client.py for other API / local models.

Build Lean dependencies:

```
lake build
```

Run the app with
```
streamlit run lean_agent/app.py --server.address 127.0.0.1
```
The frontend was largely vibecoded during a hackathon and may not be super safe.
I tried to add some safety checks, but this is not hardened software.
I recommended to run it locally and avoid exposing it to the public network.

---

### Future Work

- I'll try to turn it into a VSCode extension.
- Parallel compilation could be useful.

Note that this is not tactic-level proof interaction (no info on the intermediate goals). It is also dependent on LLM quality (Mistral works well here).

Props to Mistral, Iterate and all the staff and sponsors for organizing the hackathon and providing us with tips, coffee, and food. 🫶