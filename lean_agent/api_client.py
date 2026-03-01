import os
import json
import re
from typing import Any

try:
    from mistralai.client import Mistral
except Exception:
    from mistralai import Mistral

MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
API_KEY = os.getenv("MISTRAL_API_KEY") # please don't hardcode any API key

if not API_KEY:
    raise RuntimeError("Missing env var MISTRAL_API_KEY")

client = Mistral(api_key=API_KEY)


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content)
    if isinstance(content, list):
        parts: list[str] = []
        for x in content:
            if x is None:
                continue
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                if isinstance(x.get("text"), str):
                    parts.append(x["text"])
                elif isinstance(x.get("content"), str):
                    parts.append(x["content"])
                else:
                    parts.append(json.dumps(x))
            else:
                parts.append(str(x))
        return "".join(parts)
    return str(content)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_first_json_object(text: str) -> str:
    s = text
    start = s.find("{")
    if start == -1:
        raise ValueError
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    raise ValueError


def _to_json(content: Any) -> dict:
    text = _strip_fences(_flatten_content(content))
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    try:
        return json.loads(_extract_first_json_object(text))
    except Exception as e:
        raise ValueError(f"Invalid JSON response:\n{text}") from e


def chat_json(messages, max_tokens=1400, temperature=0.1) -> dict:
    resp = client.chat.complete(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        response_format={"type": "json_object"},
    )
    return _to_json(resp.choices[0].message.content)


def repair_json(bad_text: str) -> dict:
    return chat_json(
        [
            {
                "role": "system",
                "content": "Return STRICT valid JSON only. No markdown. One object.",
            },
            {"role": "user", "content": bad_text},
        ],
        max_tokens=800,
        temperature=0.0,
    )