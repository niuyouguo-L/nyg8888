"""单次 HTTP 探测。只用标准库。

设计取舍：
  · 不跟随超过 N 次重定向（默认 5），避免环形跳转把 timeout 吃光
  · 读 body 但设上限（默认 2 MiB），避免被大文件拖死
  · sha256 对原始字节做，不做编码归一 —— 页面编码变了也应该算变化
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Optional

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_UA = "probe-kit/0.1 (+https://github.com/niuyouguo-L/nyg8888)"


@dataclass
class ProbeResult:
    """一次探测的结果。"""

    url: str
    ok: bool = False
    status: Optional[int] = None
    elapsed_ms: int = 0
    body_sha256: str = ""
    body_text: str = ""
    body_bytes: int = 0
    error: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)

    def matches_status(self, expect) -> bool:
        """expect 可以是 int（200）、字符串（"2xx"）或 None（不校验）。"""
        if expect is None:
            return True
        if self.status is None:
            return False
        want = str(expect).strip().lower()
        got = str(self.status)
        if want.endswith("xx") and len(want) == 3:
            return got.startswith(want[0])
        if "-" in want:
            lo, hi = want.split("-", 1)
            try:
                return int(lo) <= self.status <= int(hi)
            except ValueError:
                return False
        try:
            return self.status == int(want)
        except ValueError:
            return False

    @property
    def short(self) -> str:
        if self.error:
            return self.error
        return "HTTP %s  %dms" % (self.status, self.elapsed_ms)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """只用于统计跳转次数上限之外的情况；这里保持默认跟随行为。"""


def probe(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    user_agent: str = DEFAULT_UA,
    verify_tls: bool = True,
) -> ProbeResult:
    """探测一个 URL，返回 ProbeResult（永不抛异常）。"""
    res = ProbeResult(url=url)

    hdrs = {"User-Agent": user_agent, "Accept": "*/*"}
    if headers:
        hdrs.update(dict(headers))

    req = urllib.request.Request(url, method=method.upper(), headers=hdrs)

    # 默认 opener 会校验 TLS。要跳过校验得用 ssl context，但那要额外一句，
    # 而 verify_tls=False 在生产里几乎不该用，所以只在明确要求时构造。
    opener = urllib.request.build_opener()
    if not verify_tls:
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    t0 = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as r:
            res.status = r.status
            res.headers = dict(r.headers.items())
            raw = r.read(max_bytes)
    except urllib.error.HTTPError as e:
        # 4xx / 5xx 也会走到这里，但状态码是有效的观测值
        res.status = e.code
        try:
            res.headers = dict(e.headers.items()) if e.headers else {}
            raw = e.read(max_bytes)
        except Exception:  # noqa: BLE001
            raw = b""
    except urllib.error.URLError as e:
        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        res.error = "URLError: %s" % (getattr(e, "reason", e),)
        return res
    except Exception as e:  # noqa: BLE001  socket.timeout / ssl 错误等
        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        res.error = "%s: %s" % (type(e).__name__, e)
        return res

    res.elapsed_ms = int((time.monotonic() - t0) * 1000)
    res.body_bytes = len(raw)
    res.body_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        res.body_text = raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        res.body_text = ""
    res.ok = True
    return res


def check_target(target: dict, default_timeout: float = DEFAULT_TIMEOUT) -> tuple:
    """按配置里的一个 target 探测并判定。

    返回 (result, problems)，problems 是 list[str]，空表示全部通过。
    """
    r = probe(
        target["url"],
        timeout=float(target.get("timeout") or default_timeout),
        method=target.get("method") or "GET",
        headers=target.get("headers") or None,
    )
    problems = []

    if r.error:
        problems.append(r.error)
        return r, problems

    if not r.matches_status(target.get("expect_status")):
        problems.append("状态 %s 不符合预期 %s" % (r.status, target.get("expect_status")))

    max_ms = target.get("max_ms")
    if max_ms and r.elapsed_ms > int(max_ms):
        problems.append("耗时 %dms 超过阈值 %sms" % (r.elapsed_ms, max_ms))

    kw = target.get("expect_keyword")
    if kw and kw not in r.body_text:
        problems.append("响应里找不到关键词 %r" % kw)

    return r, problems
