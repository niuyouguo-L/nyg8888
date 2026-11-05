"""命令行入口。

    probe-kit check  --config config.toml [--state .probe-state.json]
    probe-kit probe  <url> [--timeout 10]
    probe-kit init   [--out config.toml]

退出码：
    0  全部正常
    1  有目标失败
    2  配置错误
    3  全部正常，但有内容变化
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config as cfgmod, notify
from .probe import DEFAULT_TIMEOUT, check_target, probe
from .state import State

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CFG = 2
EXIT_CHANGED = 3


def _say(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def cmd_check(args) -> int:
    try:
        cfg = cfgmod.load_auto(args.config)
    except cfgmod.ConfigError as e:
        print("配置错误: %s" % e, file=sys.stderr)
        return EXIT_CFG

    targets = cfg["targets"]
    st = State(args.state).load()
    default_to = float(cfg.get("timeout") or DEFAULT_TIMEOUT)

    failed, changed, lines = [], [], []

    for t in targets:
        name = t["name"]
        r, problems = check_target(t, default_to)

        watch = bool(t.get("watch_content"))
        sha_changed = False
        if r.ok and watch:
            old = st.get_sha(name)
            sha_changed = bool(old) and old != r.body_sha256
            if sha_changed:
                problems.append("内容变化 %s → %s" % (old[:8], r.body_sha256[:8]))
            st.set(name, sha=r.body_sha256, status=r.status)
        elif r.ok:
            st.set(name, sha=r.body_sha256 if watch else "", status=r.status)

        if problems:
            tag = "chg" if (sha_changed and len(problems) == 1) else "FAIL"
            if tag == "chg":
                changed.append(name)
            else:
                failed.append(name)
            lines.append("[%-4s] %-16s %s" % (tag, name, "; ".join(problems)))
        else:
            lines.append("[ok]   %-16s %s" % (name, r.short))

    st.save()

    print("\n".join(lines))

    if failed:
        _notify(cfg, "probe-kit: %d 个目标异常\n%s"
                % (len(failed), "\n".join(lines)))
        return EXIT_FAIL
    if changed:
        _notify(cfg, "probe-kit: %d 个目标内容变化\n%s"
                % (len(changed), "\n".join(lines)))
        return EXIT_CHANGED
    return EXIT_OK


def _notify(cfg: dict, text: str) -> None:
    ncfg = cfg.get("notify") or {}
    if not ncfg:
        return
    for chan, ok, detail in notify.send(text, ncfg):
        print("[notify] %s %s %s" % (chan, "ok" if ok else "失败", detail[:120]),
              file=sys.stderr)


def cmd_probe(args) -> int:
    r = probe(args.url, timeout=args.timeout)
    if r.error:
        print("失败: %s" % r.error)
        return EXIT_FAIL
    print("URL      %s" % r.url)
    print("状态     %s" % r.status)
    print("耗时     %dms" % r.elapsed_ms)
    print("大小     %d 字节" % r.body_bytes)
    print("sha256   %s" % r.body_sha256)
    if args.body:
        print("---")
        print(r.body_text[:2000])
    return EXIT_OK if (200 <= (r.status or 0) < 400) else EXIT_FAIL


TEMPLATE = '''# probe-kit 配置示例
# 每个 [[targets]] 是一个探测目标

[notify]
# 三选一，不配就只打印到终端
# webhook   = "https://your-endpoint/hook"
# serverchan = "SCT..."
# pushplus   = ""

[[targets]]
name = "example-api"
url  = "https://httpbin.org/status/200"
expect_status = 200
timeout = 10
max_ms = 3000

[[targets]]
name = "example-json"
url  = "https://httpbin.org/json"
expect_status = "2xx"
watch_content = true
'''


def cmd_init(args) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        print("已存在 %s（加 --force 覆盖）" % out, file=sys.stderr)
        return EXIT_CFG
    out.write_text(TEMPLATE, encoding="utf-8")
    print("已写入 %s" % out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="probe-kit",
        description="轻量网站 / API 探测工具（零依赖）",
    )
    ap.add_argument("--version", action="version", version="probe-kit %s" % __version__)
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("check", help="按配置批量探测")
    p1.add_argument("--config", "-c", default="config.toml")
    p1.add_argument("--state", "-s", default=".probe-state.json")
    p1.add_argument("--quiet", "-q", action="store_true")

    p2 = sub.add_parser("probe", help="探测单个 URL")
    p2.add_argument("url")
    p2.add_argument("--timeout", "-t", type=float, default=DEFAULT_TIMEOUT)
    p2.add_argument("--body", action="store_true", help="打印响应体前 2000 字节")

    p3 = sub.add_parser("init", help="生成配置模板")
    p3.add_argument("--out", "-o", default="config.toml")
    p3.add_argument("--force", action="store_true")

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return EXIT_OK
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "probe":
        return cmd_probe(args)
    if args.cmd == "init":
        return cmd_init(args)
    ap.print_help()
    return EXIT_CFG


if __name__ == "__main__":
    sys.exit(main())
