"""通知发送。只支持 POST 一个 JSON —— 够用，且不会因为某个平台改接口就全体失效。"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

DEFAULT_TIMEOUT = 8.0


def _post_json(url: str, payload: dict, timeout: float = DEFAULT_TIMEOUT) -> tuple:
    """POST 一个 JSON，返回 (ok, detail)。永不抛异常。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "probe-kit/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read(4096).decode("utf-8", "replace")
            return (200 <= r.status < 300), txt[:300]
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def _post_form(url: str, fields: dict, timeout: float = DEFAULT_TIMEOUT) -> tuple:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "User-Agent": "probe-kit/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read(4096).decode("utf-8", "replace")
            return (200 <= r.status < 300), txt[:300]
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def send(text: str, cfg: Optional[dict] = None, *, title: str = "probe-kit") -> list:
    """按配置发通知。cfg 里没配任何渠道就什么都不做。

    返回 [(channel, ok, detail), ...]
    """
    cfg = cfg or {}
    results = []

    hook = cfg.get("webhook")
    if hook:
        ok, detail = _post_json(hook, {"title": title, "text": text})
        results.append(("webhook", ok, detail))

    sc = cfg.get("serverchan") or cfg.get("server_chan")
    if sc:
        ok, detail = _post_form(
            "https://sctapi.ftqq.com/%s.send" % sc,
            {"title": title, "desp": text},
        )
        results.append(("serverchan", ok, detail))

    pp = cfg.get("pushplus")
    if pp:
        ok, detail = _post_json(
            "https://www.pushplus.plus/send",
            {"token": pp, "title": title, "content": text, "template": "txt"},
        )
        results.append(("pushplus", ok, detail))

    return results
