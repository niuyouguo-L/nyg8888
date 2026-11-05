# 用法说明

## 三种用法，按复杂度排

### 1. 临时看一眼某个地址

```bash
probe-kit probe https://example.com --timeout 15 --body
```

输出状态码、耗时、响应体大小、sha256，加 `--body` 还会打印前 2000 字节。

**退出码 0 表示 2xx/3xx，非 0 表示有问题。** 可以直接嵌进 shell 脚本：

```bash
probe-kit probe https://api.example.com/health || curl -X POST $HOOK -d '{"text":"挂了"}'
```

### 2. 批量检查（最常用）

```bash
probe-kit init                     # 生成 config.toml
vim config.toml                    # 填目标
probe-kit check --config config.toml
```

输出：

```
[ok]   api-health        HTTP 200  312ms
[ok]   docs-page         HTTP 200  1.2s
[chg]  price-feed        HTTP 200  890ms  内容变化 8f3a11c2 → b71e0d94
[FAIL] legacy-api        状态 502 不符合预期 200
```

退出码：

| 码 | 含义 | 适合怎么处理 |
|---|---|---|
| 0 | 全绿 | 什么都不做 |
| 1 | 有目标失败 | 告警 |
| 3 | 全绿但有内容变化 | 可选告警 |

**1 和 3 分开是有意的**：内容变化往往不是故障（价格变了、新闻更新了），
失败才是。你可以只对 1 告警，3 只记日志。

### 3. 作为库嵌进自己的脚本

```python
import sys
sys.path.insert(0, "path/to/nyg8888/src")

from probe_kit import probe, State, notify

r = probe("https://api.example.com/data", timeout=8)
if not r.ok:
    print("挂了:", r.error)
elif r.status != 200:
    print("状态异常:", r.status)
else:
    st = State("/var/lib/myscript/probe.json").load()
    old = st.get_sha("api")
    if old and old != r.body_sha256:
        notify.send("接口返回变了", {"webhook": "https://your-hook"})
    st.set("api", sha=r.body_sha256, status=r.status)
    st.save()
```

---

## 配置字段完整表

### `[notify]` 段

| 字段 | 说明 |
|---|---|
| `webhook` | POST 一个 `{"title":..., "text":...}` 到你给的地址 |
| `serverchan` | Server酱 SendKey，形如 `SCTxxxxx` |
| `pushplus` | PushPlus token |
| `timeout` | 全局默认请求超时（秒） |

### `[[targets]]` 段（每个目标一个）

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 唯一标识，状态文件里用这个名字做 key |
| `url` | ✅ | 必须 `http://` 或 `https://` |
| `expect_status` | | `200` / `"2xx"` / `"200-299"`，不填则任何状态都算通 |
| `timeout` | | 单目标超时（秒），覆盖全局 |
| `max_ms` | | 耗时阈值，超过就记问题 |
| `expect_keyword` | | 响应体必须包含的字符串 |
| `watch_content` | | `true` 时比对响应体 sha256，变了就告警 |
| `method` | | 默认 GET，可填 POST 等 |
| `headers` | | 暂只支持配置文件里的简单映射（见下） |

> `headers` 目前要从 JSON 配置里用，TOML 子集不解析 inline table。
> 需要自定义 header 时建议用 `.json` 配置：

```json
{
  "targets": [
    {
      "name": "auth-api",
      "url": "https://api.example.com/me",
      "expect_status": 200,
      "headers": {"Authorization": "Bearer xxx"}
    }
  ]
}
```

---

## 状态文件长什么样

```json
{
  "price-feed": {
    "sha256": "8f3a11c2e4d5...",
    "status": 200,
    "checked_at": "2026-11-05T21:30:12+08:00"
  }
}
```

**删掉它就等于重置**——下次所有 `watch_content` 的目标都会被当作「首次」，
不会误报变化。

写文件是原子的（先写临时文件再 rename），中途 Ctrl-C 不会留下半个 JSON。

---

## 放到 cron 里

```cron
# 每 5 分钟检查一次
*/5 * * * * cd /opt/probe-kit && /usr/bin/python3 -m probe_kit check -c config.toml -s /var/lib/probe/state.json >> /var/log/probe.log 2>&1
```

**注意用绝对路径**，cron 的工作目录和 PATH 跟交互式 shell 不一样。

## 放到 systemd timer 里

```ini
# /etc/systemd/system/probe.service
[Unit]
Description=probe-kit check

[Service]
Type=oneshot
WorkingDirectory=/opt/probe-kit
ExecStart=/usr/bin/python3 -m probe_kit check -c config.toml -s /var/lib/probe/state.json
```

```ini
# /etc/systemd/system/probe.timer
[Unit]
Description=Run probe every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now probe.timer
```

---

## 常见问题

**Q: 为什么不用 requests？**

A: 只想在 cron 里跑一条命令的场景，多一个依赖就多一份升级负担。
`urllib` 够用，而且它不会因为版本冲突突然装不上。

**Q: 为什么内容变化单独一个退出码？**

A: 因为「变了」和「坏了」是两件事。价格页面变了通常不是故障，
但你可能想知道。分开之后告警策略可以不同。

**Q: 能并发检查吗？**

A: 现在不能，串行。目标数量在几十个以内时串行完全够用（每个 1 秒内）。
真需要并发的时候再加，不想一上来就引入 threading 的复杂度。

**Q: 支持 POST 带 body 吗？**

A: 目前只支持 GET 和空 body 的 POST。需要带 body 的场景建议直接用库调用，
或者提 issue 说清楚你的用例。
