# Sync automation — the full guide

The skill's own `SKILL.md` covers the short version. This file is the long version:
what the sync does, how the scheduling works, and how to debug it.

# openclaw-magpie-sync

让 OpenClaw 自动跟上 magpie 的模型清单：**magpie 那边一改模型，OpenClaw 这边 30 分钟内（装了 launchd 则是几秒内）自动同步，不用你管。**

---

## 1. 为什么要这个东西

magpie 是本机的模型网关（`http://127.0.0.1:3425`），把你买的各家账号、免费档、路由组统一成一个 `/v1/models` 目录。它原生驱动 Hermes、Codex、Claude Code、Qwen Code、OpenCode 等 60 多个 agent，**但没有 OpenClaw**——它的 agent 列表是编译进 Go 二进制的，插件机制只能扩展 provider，不能扩展 agent。

所以 OpenClaw 必须反过来指向 magpie 的网关。这一步由 [openclaw-magpie 技能](https://github.com/MrFengcn/magpie-agent-bridge) 完成，本包是它的续集：

> 技能解决「接一次线」，本包解决「**接完之后 magpie 又加了模型怎么办**」。

关键在于：一个模型要在 `~/.openclaw/openclaw.json` 的**四个地方**同时出现才算数，少一处就会出现「选择器里看不到」或者「默认模型悄悄回退」这种查半天的怪问题：

| # | 位置 | 作用 |
|---|---|---|
| 1 | `models.providers.magpie.models[]` | provider 本身的模型表 |
| 2 | `agents.defaults.models["magpie/<id>"]` | 注册表 |
| 3 | `agents.defaults.modelPolicy.allow[]` | **最坑的一个**：漏了就选不到、默认还会回退 |
| 4 | `agents.defaults.model.primary` | 只有当它该成为默认时才写 |

手工维护这四处 + 重启网关，就是本包自动化掉的全部工作。

---

## 2. 包里有什么

```
magpie-agent-bridge/
├── SKILL.md                      ← 技能本体
├── README.md
├── scripts/
│   ├── openclaw_magpie.py        ← 接线脚本（doctor/list/install/uninstall/verify）
│   ├── magpie_openclaw_sync.py   ← 同步脚本（主角，纯标准库，Python 3.9+）
│   ├── install-sync.sh           ← 一键安装自动化
│   └── uninstall-sync.sh         ← 卸载（可选连还原接线）
├── references/
│   ├── platforms.md
│   └── magpie-openclaw-sync.plist.template   ← macOS 秒同步（__HOME__ 会被替换成真实路径）
└── tests/
    ├── test_openclaw_magpie.py
    └── test_magpie_openclaw_sync.py
```

---

## 3. 安装

```bash
bash scripts/install-sync.sh
```

它按顺序做五件事，每步都有输出：

1. 同步脚本装到 `python3 scripts/magpie_openclaw_sync.py`
2. 技能装到 `~/.hermes/skills/openclaw-magpie/`
3. 生成并加载 launchd job（macOS；监听 magpie 配置文件变化）
4. 立刻跑一次同步
5. 注册 Hermes cron 任务 `magpie→OpenClaw 模型同步`（`no_agent`，每 30 分钟）

参数：

| 参数 | 作用 |
|---|---|
| `--no-launchd` | 不装 launchd，只靠 cron |
| `--no-restart` | 写配置但不重启 OpenClaw 网关 |
| `--dry-run` | 只报告会改什么，不写任何文件 |

> 想先看看再动手：`bash scripts/install-sync.sh --dry-run --no-launchd`

**第 3 步可能加载失败**，报 `! 加载失败` —— 那是因为 Hermes 网关出于防自重启的设计，禁止在网关会话里调用 `launchctl`。在你自己的终端里跑一次就好：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.walter.magpie-openclaw-sync.plist
```

不跑也没关系，cron 每 30 分钟兜底。

---

## 4. 装完怎么确认它在工作

```bash
# 接线体检：网关在不在、四处位置是否对齐
python3 scripts/openclaw_magpie.py doctor

# 真跑一轮对话，看是否真的走了 magpie（期望 winnerProvider: magpie）
python3 scripts/openclaw_magpie.py verify \
        --model "magpie/group/cheap-first"

# 同步日志
tail -f ~/.hermes/logs/magpie-openclaw-sync.log

# cron 在不在
hermes cron list
```

还有一条铁证：magpie 按 **User-Agent** 识别调用方，所以 OpenClaw 发出的请求会以 `agent=openclaw` 出现在 `~/.config/magpie/usage.jsonl` 里。

```bash
grep '"agent":"openclaw"' ~/.config/magpie/usage.jsonl | tail -3
```

---

## 5. 自动同步的两条路

| | launchd | Hermes cron |
|---|---|---|
| 触发 | 监听 `~/.config/magpie` 及其中的 `providers.json`、`plugin-providers.json` 变化；另加每 30 分钟兜底 | 固定每 30 分钟 |
| 延迟 | 几秒 | 最多 30 分钟 |
| 成本 | 0（纯脚本） | 0（`no_agent`，不进 LLM） |
| 跨平台 | macOS only | 任何跑 Hermes 的机器 |

两条路都调用同一个脚本，且都是幂等的：没变化就什么都不做、什么都不发。

cron 之所以要 `no_agent=true`：脚本的 stdout 会被**原样投递**到聊天里，空 stdout 什么都不发。所以脚本的设计是——只有真的改了东西、或者出了需要你处理的错，才往 stdout 写；例行的「没变化」只写日志文件。否则你会每 30 分钟收到一条废话。

---

## 6. 手动同步

```bash
python3 scripts/magpie_openclaw_sync.py --dry-run   # 只看不改；退出码 2 = 有变化
python3 scripts/magpie_openclaw_sync.py             # 同步，必要时重启网关
python3 scripts/magpie_openclaw_sync.py --no-restart
python3 scripts/magpie_openclaw_sync.py --force     # 明明没变也要重写+重启
```

**它同步什么**：网关上所有的 `group/*`（路由组，会在多个账号之间自动切换，首选）和 `auto/*`（一个逻辑模型后面挂多家）。

**它不同步什么**：裸的 `provider/model` id（如 `openrouter/openai/gpt-6.1-terra`）。因为 OpenClaw 用**第一个斜杠**切分 `provider/model`，而这类 id 的模型名里本身带斜杠，会切错。要某个具体模型就用 `auto/*` 组。

**它比技能里的 `install` 多做三件事**：

1. **会删除**已经从网关消失的模型引用（`install` 只增不减，久了配置会堆垃圾）
2. **只在真变化时**重启网关（`install` 每次都叫你重启）
3. 写之前备份到 `openclaw.json.bak-magpie-sync`，写完跑 `openclaw config validate`，**校验不过自动回滚**

**它不会碰** `agents.defaults.model.primary`。如果某次删除让 primary 指向了一个不存在的模型，它只会在日志里提醒你，改不改由你决定。

---

## 7. 防呆设计

- **网关只返回少于 5 个 group/auto 模型 → 拒绝写入。** 那是 magpie 正在重启、模型目录还没加载完的瞬间；这时同步会把你的配置掏空。
- **magpie 不可达 → 静默跳过（退出码 0）。** magpie 没开是正常状态，不是故障，不值得每 30 分钟报警一次。
- **单实例锁** `~/.cache/magpie-openclaw-sync.lock`：launchd 触发和 cron 撞车时只跑一个；锁超过 15 分钟视为残留自动清理。
- **`maxTokens` 封顶 131072**：magpie 自己会宣告到 524288，超出了 OpenClaw 的天花板。
- **同时兼容 `agents.defaults.model` 的两种写法。** OpenClaw 网关在你换默认模型时会把
  它从带 `primary` 键的对象改写成裸字符串。读取时做了类型判断，两种都能读，不会因此崩掉
  （技能里原来的 `doctor` 会崩 `'str' object has no attribute 'get'`，本包已修复）。
- **`cost` 全 0**：真实价格取决于这次是哪家上游账号接的，OpenClaw 里的成本数字本来就不可信，不如不填。

---

## 8. 日志

| 文件 | 内容 |
|---|---|
| `~/.hermes/logs/magpie-openclaw-sync.log` | 每次运行的完整记录（含「没变化」） |
| `~/.hermes/logs/magpie-openclaw-sync.launchd.log` / `.err.log` | launchd 的 stdout/stderr |

---

## 9. 卸载

```bash
bash scripts/uninstall-sync.sh                 # 只拆自动化，OpenClaw 的 magpie 接线保留
bash scripts/uninstall-sync.sh --with-wiring   # 连接线一起还原到装本包之前
bash scripts/uninstall-sync.sh --purge         # 再加上删日志和备份
```

`--with-wiring` 会用技能的 `uninstall` 从 `openclaw.json.bak-openclaw-magpie` 还原配置，之后需要 `openclaw gateway stop --force && openclaw gateway start`。

---

## 10. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志里一直是 `magpie gateway unreachable` | magpie 没在跑 | `magpie autostart on`，或开一下 magpie |
| 模型同步了但 OpenClaw 里选不到 | 漏了 `modelPolicy.allow`（第 3 处） | 跑一次 `doctor`，看 `in modelPolicy` 那行 |
| 同步后 OpenClaw 报模型不存在 | 网关重启没生效 | `openclaw gateway stop --force && openclaw gateway start` |
| launchd 没触发 | job 没加载 | `launchctl print gui/$(id -u)/com.walter.magpie-openclaw-sync`；没有就按第 3 节的命令加载 |
| cron 没触发 | 任务被删或被 pause | `hermes cron list`，再跑一次 `bash scripts/install-sync.sh` 会自动补建 |
| 日志出现 `looks mid-restart` | 触发得太早，magpie 目录还没加载完 | 不用管，下一轮自动补上 |
| 网关起不来（health 空、exit 7） | `api` 字段写成了非法值 | 该字段只允许 `openai-completions` 等枚举值；`openclaw.json.bak-magpie-sync` 里有正确版本 |

---

## 版本

| 版本 | 日期 | 变化 |
|---|---|---|
| 1.0.0 | 2026-10-27 | 首个打包版。同步脚本（增删双向、真变化才重启、validate 回滚、单实例锁）+ launchd 秒同步 + Hermes cron 兜底 + install/uninstall + 本说明 |

许可：MIT（见仓库根目录的 `LICENSE`）。
