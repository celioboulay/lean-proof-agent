# NOTE
# The frontend was largely vibecoded during the hackathon.
# I tried to add some safety checks, but this is not hardened software.
# Sending arbitrary .tex files is not super safe either.
# Run locally and don't expose it publicly.
# I will make a clean version of it when I get time, or just switch to the VSCode extension?

import os
import json
import asyncio
import time
import difflib
import hashlib
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Lean Paper Agent",
    layout="wide",
    initial_sidebar_state="collapsed",
)

try:
    from lean_agent import main
    from lean_agent.axiom_api import verify_proof
except Exception as e:
    st.error(f"Backend import failed: {e}")
    st.stop()

try:
    from streamlit_ace import st_ace
except Exception:
    st_ace = None


with open("frontend/style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _append_lean4_constraint(system_prompt: str) -> str:
    add = "\n\nLEAN4 SYNTAX ONLY:\n- NEVER use `by { ... }`.\n- Use indentation blocks:\n  by\n    ...\n"
    if "LEAN4 SYNTAX ONLY" in system_prompt:
        return system_prompt
    return system_prompt.rstrip() + add


def _append_no_fake_imports(system_prompt: str) -> str:
    add = (
        "\n\nIMPORT CONSTRAINTS:\n"
        "- Do NOT invent module names.\n"
        "- Do NOT import or reference: Mathlib.Algebra.Parity, Mathlib.Data.Nat.Parity.\n"
        "- Prefer minimal imports; if unsure whether a module exists, do not import it.\n"
    )
    if "IMPORT CONSTRAINTS" in system_prompt:
        return system_prompt
    return system_prompt.rstrip() + add


def _read_work_lean() -> str:
    try:
        return Path(main.LEAN_FILE).read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_latex_envs(doc: str) -> list[dict]:
    stmt_pat = re.compile(
        r"\\begin\{(?P<env>theorem|lemma|proposition|corollary)\}(?:\[[^\]]*\])?\s*(?P<body>.*?)\\end\{(?P=env)\}",
        re.DOTALL | re.IGNORECASE,
    )
    proof_pat = re.compile(
        r"\\begin\{proof\}(?:\[[^\]]*\])?\s*(?P<body>.*?)\\end\{proof\}",
        re.DOTALL | re.IGNORECASE,
    )

    matches = []
    for m in stmt_pat.finditer(doc):
        matches.append(("stmt", m.start(), m.end(), m.group("env").lower(), m.group("body")))
    for m in proof_pat.finditer(doc):
        matches.append(("proof", m.start(), m.end(), "proof", m.group("body")))
    matches.sort(key=lambda x: x[1])

    items = []
    i = 0
    while i < len(matches):
        kind, s, e, env, body = matches[i]
        if kind != "stmt":
            i += 1
            continue

        statement = (body or "").strip()
        proof = ""
        span_stmt = (s, e)
        span_full = (s, e)

        j = i + 1
        if j < len(matches):
            k2, s2, e2, _, body2 = matches[j]
            gap = doc[e:s2]
            if k2 == "proof" and (gap.strip() == ""):
                proof = (body2 or "").strip()
                span_full = (s, e2)
                i = j

        item_id = _h(f"latex|{env}|{statement}|{proof}|{span_full}")
        items.append(
            {
                "id": item_id,
                "kind": env,
                "statement": statement,
                "proof": proof,
                "span_stmt": span_stmt,
                "span_full": span_full,
            }
        )
        i += 1

    return items


@st.cache_data(show_spinner=False)
def parse_document(doc: str) -> list[dict]:
    if any(x in doc for x in ("\\begin{theorem}", "\\begin{lemma}", "\\begin{proposition}", "\\begin{corollary}")):
        items = _parse_latex_envs(doc)
        return items
    return []


def _build_problem_text(item: dict) -> str:
    if item.get("proof"):
        return f"Statement:\n{item['statement']}\n\nInformal proof:\n{item['proof']}\n"
    return f"Statement:\n{item['statement']}\n"


def run_loop(problem_text: str, max_iters: int, system_prompt: str):
    main.SYSTEM = system_prompt

    history: list[dict] = []
    last_error = ""
    full_log = ""
    attempts: list[dict] = []
    t_start = time.perf_counter()

    for i in range(1, max_iters + 1):
        t_iter = time.perf_counter()

        obj = main.one_attempt(problem_text, last_error, history)
        if not isinstance(obj, dict):
            obj = main.repair_json(json.dumps(obj))

        theorem_statement = (obj.get("theorem_statement") or "").strip()
        proof = (obj.get("proof") or "").strip()
        helpers = (obj.get("helpers") or "").strip()

        if not theorem_statement.startswith("theorem target") or not theorem_statement.endswith(":="):
            last_error = "Bad theorem_statement format. Must be: theorem target (...) : ... :="
            full_log += f"\nITER {i}\nFAIL (format)\n{last_error}\n"
            attempts.append({"iter": i, "status": "FAIL (format)", "time_s": time.perf_counter() - t_iter, "lean": _read_work_lean()})
            history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})
            continue

        if not proof.startswith("by"):
            last_error = "Bad proof format. Must start with: by"
            full_log += f"\nITER {i}\nFAIL (format)\n{last_error}\n"
            attempts.append({"iter": i, "status": "FAIL (format)", "time_s": time.perf_counter() - t_iter, "lean": _read_work_lean()})
            history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})
            continue

        if "import " in helpers:
            last_error = "helpers must not contain import lines"
            full_log += f"\nITER {i}\nFAIL (helpers)\n{last_error}\n"
            attempts.append({"iter": i, "status": "FAIL (helpers)", "time_s": time.perf_counter() - t_iter, "lean": _read_work_lean()})
            history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})
            continue

        fe = main._forbidden_error("\n".join([main.IMPORTS, helpers, theorem_statement, proof]))
        if fe:
            last_error = fe
            full_log += f"\nITER {i}\nFAIL (forbidden)\n{last_error}\n"
            attempts.append({"iter": i, "status": "FAIL (forbidden)", "time_s": time.perf_counter() - t_iter, "lean": _read_work_lean()})
            history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})
            continue

        main.write_file(main.IMPORTS, theorem_statement, proof, helpers)
        lean_now = _read_work_lean()

        try:
            res = asyncio.run(verify_proof(file=str(main.LEAN_FILE)))
        except Exception as e:
            last_error = str(e)
            full_log += f"\nITER {i}\nFAIL (api)\n{last_error}\n"
            attempts.append({"iter": i, "status": "FAIL (api)", "time_s": time.perf_counter() - t_iter, "lean": lean_now})
            history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})
            continue

        if res.okay:
            full_log += f"\nITER {i}\nVERIFIED\n"
            attempts.append({"iter": i, "status": "VERIFIED", "time_s": time.perf_counter() - t_iter, "lean": lean_now})
            elapsed_total = time.perf_counter() - t_start
            return True, full_log, attempts, elapsed_total

        last_error = main._format_axle_output(res)
        full_log += f"\nITER {i}\n{last_error[-2000:]}\n"
        attempts.append({"iter": i, "status": "FAIL (lean)", "time_s": time.perf_counter() - t_iter, "lean": lean_now})
        history.append({"helpers": helpers, "theorem_statement": theorem_statement, "proof": proof, "error": last_error})

    elapsed_total = time.perf_counter() - t_start
    return False, full_log, attempts, elapsed_total


def _reset_results():
    st.session_state["results"] = {}
    st.session_state["focus"] = None


def _set_running(item_id: str, val: bool):
    st.session_state.setdefault("running", {})
    st.session_state["running"][item_id] = val


def _is_running(item_id: str) -> bool:
    return bool(st.session_state.get("running", {}).get(item_id, False))


def _run_item(item: dict, max_iters: int, sys_prompt: str, do_rerun=True):
    item_id = item["id"]
    if _is_running(item_id):
        return
    _set_running(item_id, True)
    try:
        sp = _append_no_fake_imports(_append_lean4_constraint(sys_prompt))
        problem_text = _build_problem_text(item)
        ok, log, attempts, elapsed = run_loop(problem_text, max_iters, sp)

        st.session_state.setdefault("results", {})
        st.session_state["results"][item_id] = {
            "ok": ok,
            "status": "VERIFIED" if ok else "FAIL",
            "log": log,
            "attempts": attempts,
            "elapsed": elapsed,
            "lean": attempts[-1]["lean"] if attempts else "",
            "ts": time.time(),
            "kind": item["kind"],
        }
        if do_rerun:
            st.rerun()
    finally:
        _set_running(item_id, False)


def _attempts_table(attempts: list[dict]) -> list[dict]:
    return [{"iter": a["iter"], "status": a["status"], "time_s": round(a["time_s"], 2)} for a in attempts]


def _badge_html(status: str) -> str:
    if status == "VERIFIED":
        return '<span class="badge badge-ok">VERIFIED</span>'
    if status == "FAIL":
        return '<span class="badge badge-fail">FAIL</span>'
    return '<span class="badge badge-pending">PENDING</span>'


def _disable_spellcheck_js():
    components.html(
        """
<script>
setTimeout(function(){
  const doc = parent.document;
  const tas = doc.querySelectorAll('textarea');
  tas.forEach(t => {
    t.spellcheck = false;
    t.setAttribute("spellcheck","false");
    t.setAttribute("autocorrect","off");
    t.setAttribute("autocapitalize","off");
  });
}, 50);
</script>
""",
        height=0,
    )


def _render_editor() -> str:
    if st_ace is not None:
        value = st_ace(
            value=st.session_state["doc"],
            language="latex",
            theme="textmate",
            keybinding="vscode",
            font_size=14,
            tab_size=2,
            show_gutter=True,
            show_print_margin=False,
            wrap=True,
            auto_update=True,
            min_lines=45,
            max_lines=45,
            key="latex_editor",
        )
        return st.session_state["doc"] if value is None else value

    _disable_spellcheck_js()
    return st.text_area("main.tex", value=st.session_state["doc"], height=760, label_visibility="collapsed")


SAMPLE_TEX = r"""
\section{Tiny demo note}

The app detects theorem-like blocks and generates Lean formalizations checked by the compiler.

\begin{theorem}[Order on $\mathbb{R}$]
If $x \ge 1$ then $x \ge 0$.
\end{theorem}
\begin{proof}
We know $1 \ge 0$. Together with $x \ge 1$, transitivity gives $x \ge 0$.
\end{proof}

\begin{theorem}[A small algebraic identity]
For all real numbers $a,b$, if $a=b$ then $a-b=0$.
\end{theorem}
\begin{proof}
Rewrite using the hypothesis $a=b$.
\end{proof}
""".strip()


st.title("Lean Paper Agent")
st.caption("Edit a .tex snippet like Overleaf, detect theorem blocks, run per-result formalization, inspect Lean/logs/diffs.")

if not os.getenv("MISTRAL_API_KEY"):
    st.warning("MISTRAL_API_KEY not set. UI works, but runs will fail.")

st.session_state.setdefault("doc", SAMPLE_TEX)
st.session_state.setdefault("sys_prompt", main.SYSTEM)
st.session_state.setdefault("results", {})
st.session_state.setdefault("upload_hash", "")
st.session_state.setdefault("focus", None)
st.session_state.setdefault("max_iters", 8)

with st.sidebar:
    st.markdown("### Project")
    up = st.file_uploader("Upload .tex", type=["tex"], accept_multiple_files=False)
    if up is not None:
        raw = up.getvalue()
        uh = hashlib.sha256(raw).hexdigest()
        if uh != st.session_state.get("upload_hash", ""):
            st.session_state["upload_hash"] = uh
            st.session_state["doc"] = raw.decode("utf-8", errors="replace")
            _reset_results()
            st.success(f"Loaded: {up.name}")

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Load sample", use_container_width=True):
            st.session_state["doc"] = SAMPLE_TEX
            st.session_state["upload_hash"] = ""
            _reset_results()
    with c2:
        if st.button("Clear", use_container_width=True):
            _reset_results()

    st.markdown("### Agent")
    if st.checkbox("Show SYSTEM prompt", value=False):
        st.session_state["sys_prompt"] = st.text_area("SYSTEM", value=st.session_state["sys_prompt"], height=260)

    st.session_state["max_iters"] = st.slider("Max iters / item", 1, 20, int(st.session_state["max_iters"]))

    st.caption(f"Backend writes to: {main.LEAN_FILE}")

left, right = st.columns([1.6, 1.1], gap="large")



with left:
    st.markdown('<div class="editor-label">main.tex</div>', unsafe_allow_html=True)
    doc = _render_editor()
    st.session_state["doc"] = doc



with right:
    items = parse_document(st.session_state["doc"])
    st.markdown("#### Results")
    st.markdown(f'<div class="small results-title">Found <b>{len(items)}</b> block(s).</div>', unsafe_allow_html=True)

    with st.expander("Detected results", expanded=True):
        top1, top2 = st.columns([1.15, 1.1])
        with top1:
            run_all = st.button("Run all", use_container_width=True)
        with top2:
            show_only_failed = st.checkbox("Show only failed", value=False)

        if not items:
            st.info("No theorem/lemma/proposition/corollary blocks detected.")
        else:
            if run_all:
                for it in items:
                    _run_item(it, int(st.session_state["max_iters"]), st.session_state["sys_prompt"], False)
                st.rerun()

            results = st.session_state.get("results", {})

            for idx, it in enumerate(items, start=1):
                rid = it["id"]
                res = results.get(rid)

                if show_only_failed and (res is None or res.get("ok", False)):
                    continue

                title = f"{it['kind'].title()} {idx}"
                preview = it["statement"].strip().replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:120] + "…"

                status = "PENDING" if res is None else ("VERIFIED" if res.get("ok") else "FAIL")

                row = st.columns([3.4, 1.1, 1.0])
                with row[0]:
                    st.markdown(f"**{title}** — {preview}")
                with row[1]:
                    st.markdown(_badge_html(status), unsafe_allow_html=True)
                with row[2]:
                    if st.button("Run", key=f"run_{rid}", disabled=_is_running(rid), use_container_width=True):
                        _run_item(it, int(st.session_state["max_iters"]), st.session_state["sys_prompt"])

                with st.expander("Details", expanded=False):
                    tabs = st.tabs(["Lean", "Log", "Diff", "Attempts"])
                    with tabs[0]:
                        st.code("" if res is None else res.get("lean", ""), language="lean")
                    with tabs[1]:
                        if res is None:
                            st.code("", language="text")
                        else:
                            st.write(f"Elapsed: {res.get('elapsed', 0.0):.2f}s")
                            st.code(res.get("log", ""), language="text")
                    with tabs[2]:
                        if res is None or not res.get("attempts") or len(res["attempts"]) < 2:
                            st.info("Need at least 2 attempts to diff.")
                        else:
                            a_txt = res["attempts"][-2]["lean"]
                            b_txt = res["attempts"][-1]["lean"]
                            d = difflib.unified_diff(
                                a_txt.splitlines(),
                                b_txt.splitlines(),
                                fromfile=f"iter_{res['attempts'][-2]['iter']}",
                                tofile=f"iter_{res['attempts'][-1]['iter']}",
                                lineterm="",
                            )
                            st.code("\n".join(d), language="diff")
                    with tabs[3]:
                        st.table([] if res is None else _attempts_table(res.get("attempts", [])))