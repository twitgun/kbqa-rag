"""从模型输出中提取 JSON（V-01）。

三种脏形态：
  A 纯 JSON
  B ```json 围栏
  C 前后带解释文字
"""

from __future__ import annotations

import json

from kbqa.core.validation.types import ParseError


def _strip_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json(raw: str) -> dict:
    text = _strip_fence(raw.strip())

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        raise ParseError("no_json_object")

    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i + 1])
                    except json.JSONDecodeError as exc:
                        raise ParseError(f"bad_json: {exc}") from exc
                    if isinstance(data, dict):
                        return data
                    raise ParseError("json_not_object")
    raise ParseError("unbalanced_braces")
