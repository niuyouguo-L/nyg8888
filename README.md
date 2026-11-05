# probe-kit

轻量级网站 / API 探测工具集。零第三方依赖，只用 Python 标准库。

用来回答三个问题：**它还活着吗？内容变了吗？出问题时怎么第一时间知道？**

## 为什么又造一个

现有的监控工具（Uptime Kuma、Gatus 之类）都很好，但它们需要跑一个服务、开一个面板、占一份数据库。
很多时候你只是想在 cron 里跑一条命令，检查十几个 endpoint，有问题发条消息到群里。

`probe-kit` 就是那个命令。

- **零依赖** — 只用 `urllib`、`json`、`hashlib`，不装 `requests`
- **无状态** — 状态存在一个 JSON 文件里，删掉就等于重置
- **可嵌入** — 三个函数就能用，也可以当 CLI 跑

## 安装

```bash
git clone https://github.com/niuyouguo-L/nyg8888.git
cd nyg8888
pip install -e .
```

或者不安装，直接跑：

```bash
python -m probe_kit --config examples/config.toml
```

## 快速开始

写一份配置：

```toml
[notify]
webhook = "https://example.com/hook"

[[targets]]
name = "api-health"
url  = "https://httpbin.org/status/200"
expect_status = 200
timeout = 10

[[targets]]
name = "docs-page"
url  = "https://example.com/docs"
watch_content = true      # 内容变化就告警
```

跑一次：

```bash
probe-kit check --config examples/config.toml
```

输出：

```
[ok]   api-health   200  312ms
[chg]  docs-page    200  1.2s  content changed (sha256 8f3a11c2 -> b71e0d94)
```

放到 cron 里，每 5 分钟检查一次：

```cron
*/5 * * * * cd /opt/probe-kit && probe-kit check --config config.toml --state .probe-state.json
```

## 它能检测的

| 类型 | 判断依据 |
|---|---|
| 可用性 | HTTP 状态码是否符合预期（支持区间，如 `2xx`） |
| 延迟 | 单次请求耗时，超过阈值告警 |
| 内容变化 | 响应体 sha256 与上次不同 |
| 关键词 | 响应体是否包含指定字符串 |
| 超时 | 连接 / 读取分别计时 |

## 通知

支持三种，都是 POST 一个 JSON：

```toml
[notify]
webhook = "https://your-endpoint"     # 通用 webhook
# 或
serverchan = "SCT..."                 # Server酱
# 或
pushplus = "..."                      # PushPlus
```

不配置就只打印到 stdout，退出码非零表示有异常，可以接 `&&` / `||`。

## 作为库用

```python
from probe_kit import probe, diff, notify

r = probe("https://httpbin.org/json", timeout=10)
print(r.status, r.elapsed_ms, r.body_sha256)

if diff.changed(".state.json", "httpbin", r.body_sha256):
    notify.send({"text": "httpbin 内容变了"})
```

## 状态文件

默认写到 `--state` 指定的路径，不指定则不落盘（每次都是「首次」）。

```json
{
  "httpbin": {
    "sha256": "8f3a11c2...",
    "status": 200,
    "checked_at": "2026-11-05T21:30:12+08:00"
  }
}
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 全部正常 |
| 1 | 有目标失败 |
| 2 | 配置错误 |
| 3 | 全部正常但有内容变化 |

方便直接用 `probe-kit check --quiet || echo "有异常"`。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 许可

MIT
