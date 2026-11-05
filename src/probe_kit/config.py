"""配置文件解析。

为什么不用 tomllib：3.11 才内置，而 3.9/3.10 要额外装 tomli，
就违背了「零依赖」这条。这里实现 TOML 的一个子集，正好够监测配置用：

    # 注释
    [notify]
    webhook = "https://..."

    [[targets]]
    name = "x"
    url  = "https://..."
    timeout = 10
    watch_content = true

不支持：多行字符串、日期时间、inline table、数组字面量。
遇到不认识的行会抛 ConfigError，而不是静默跳过 —— 配置写错应该立刻知道。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_KEY_VAL = re.compile(r'^([A-Za-z0-9_.-]+)\s*=\s*(.+)$')


class ConfigError(Exception):
    """配置有问题。"""


def _parse_value(raw: str) -> Any:
    v = raw.strip()
    if not v:
        return ""

    # 去掉行尾注释（引号内的 # 不算）
    if v[0] in ('"', "'"):
        q = v[0]
        end = v.rfind(q)
        if end <= 0:
            raise ConfigError("引号没闭合: %s" % raw)
        inner = v[1:end]
        if q == '"':
            inner = inner.encode().decode("unicode_escape")
        return inner

    # 数字 / 布尔 / 裸字符串
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    # 裸字符串（容忍，但去掉可能的 # 注释）
    if "#" in v:
        v = v.split("#", 1)[0].strip()
    return v


def loads(text: str) -> dict:
    """把 TOML 子集解析成 dict。"""
    root: dict = {}
    current = root
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        # [[array of tables]]
        if s.startswith("[[") and s.endswith("]]"):
            name = s[2:-2].strip()
            if not name:
                raise ConfigError("第 %d 行：[[ ]] 里没名字" % lineno)
            arr = root.setdefault(name, [])
            if not isinstance(arr, list):
                raise ConfigError("第 %d 行：%s 之前已作为表用过" % (lineno, name))
            item: dict = {}
            arr.append(item)
            current = item
            continue

        # [table]
        if s.startswith("[") and s.endswith("]"):
            name = s[1:-1].strip()
            if not name:
                raise ConfigError("第 %d 行：[ ] 里没名字" % lineno)
            node = root.setdefault(name, {})
            if not isinstance(node, dict):
                raise ConfigError("第 %d 行：%s 之前已作为数组用过" % (lineno, name))
            current = node
            continue

        # key = value
        m = _KEY_VAL.match(s)
        if not m:
            raise ConfigError("第 %d 行看不懂：%s" % (lineno, line))
        key, rawval = m.group(1), m.group(2)
        current[key] = _parse_value(rawval)

    return root


def load(path) -> dict:
    """从文件读配置。"""
    p = Path(path)
    if not p.exists():
        raise ConfigError("配置文件不存在: %s" % p)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError("读不了 %s: %s" % (p, e)) from e
    cfg = loads(text)
    _validate(cfg)
    return cfg


def load_json(path) -> dict:
    """也支持直接喂 JSON —— 用程序生成配置时更方便。"""
    p = Path(path)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ConfigError("JSON 解析失败 %s: %s" % (p, e)) from e
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    targets = cfg.get("targets")
    if targets is None:
        raise ConfigError("配置里必须有至少一个 [[targets]]")
    if not isinstance(targets, list) or not targets:
        raise ConfigError("[[targets]] 必须是非空数组")
    seen = set()
    for i, t in enumerate(targets, 1):
        if not isinstance(t, dict):
            raise ConfigError("第 %d 个 target 不是表" % i)
        name = t.get("name")
        if not name:
            raise ConfigError("第 %d 个 target 缺 name" % i)
        if name in seen:
            raise ConfigError("target 名字重复: %s" % name)
        seen.add(name)
        url = t.get("url")
        if not url:
            raise ConfigError("target %s 缺 url" % name)
        if not str(url).startswith(("http://", "https://")):
            raise ConfigError("target %s 的 url 必须是 http(s)://" % name)


def load_auto(path) -> dict:
    """按扩展名选解析器。"""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return load_json(p)
    return load(p)
