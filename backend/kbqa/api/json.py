"""统一 JSON 响应：显式声明 charset=utf-8。

不声明 charset 时，Starlette 的 JSONResponse 只发 `application/json`，
部分客户端（含 Windows PowerShell）会按 ISO-8859-1 解码，中文全变乱码。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")
