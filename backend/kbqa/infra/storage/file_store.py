"""文件落盘：按 hash 前缀分目录，原子写。"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, data: bytes, ext: str) -> tuple[str, str]:
        sha = hashlib.sha256(data).hexdigest()
        rel = f"{sha[:2]}/{sha}.{ext.lower().lstrip('.')}"
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return sha, rel

    def path_of(self, rel: str) -> Path:
        return self.root / rel

    def delete(self, rel: str) -> bool:
        p = self.root / rel
        if p.exists():
            p.unlink()
            return True
        return False

    def free_space_gb(self) -> float:
        target = self.root if self.root.exists() else Path(".")
        return shutil.disk_usage(target).free / 1024**3
