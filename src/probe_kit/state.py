"""状态文件：记录每个 target 上次的 sha256 / 状态，用于判断「内容变了」。

刻意做成极简：一个 JSON 文件，一个 dict。没有锁，没有 WAL。
并发写同一个状态文件的场景不在设计目标内 —— cron 是串行的。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


class State:
    """读写探测状态。

    用法：
        st = State(".probe-state.json")
        st.load()
        old = st.get_sha("httpbin")
        st.set("httpbin", sha="...", status=200)
        st.save()
    """

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self._data: dict = {}

    # ── 读写 ──────────────────────────────────────────────
    def load(self) -> "State":
        if not self.path or not self.path.exists():
            return self
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001  坏文件当空处理，别让监控自己挂掉
            self._data = {}
        return self

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        # 原子写：先写临时文件再 rename，避免中途 Ctrl-C 留下半个 JSON
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".probe-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(blob)
                fh.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ── 查询 ──────────────────────────────────────────────
    def get(self, name: str) -> dict:
        return self._data.get(name) or {}

    def get_sha(self, name: str) -> str:
        return (self.get(name).get("sha256") or "")

    def set(self, name: str, *, sha: str = "", status=None, extra: Optional[dict] = None) -> None:
        rec = {
            "sha256": sha,
            "status": status,
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if extra:
            rec.update(extra)
        self._data[name] = rec

    def names(self) -> list:
        return sorted(self._data.keys())

    def __len__(self) -> int:
        return len(self._data)
