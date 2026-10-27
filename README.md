# openclaw-magpie

**Let OpenClaw use magpie.** magpie natively drives Hermes, Codex, Claude Code,
Qwen Code, OpenCode, dsh and ~60 other agents — but not OpenClaw. This skill is the
bridge for that one gap.

Cross-platform: **macOS, Windows, Linux**. Python 3.9+, standard library only.

---

## Why this exists

magpie is a local gateway that speaks OpenAI Chat Completions, OpenAI Responses and
Anthropic Messages. Every agent that accepts a base URL can talk to it.

But magpie's **agent** list is compiled into its Go binary, and its plugin mechanism
extends *providers*, not agents. So magpie will never list OpenClaw as an agent:

```
$ magpie openclaw
magpie: unknown agent "openclaw" (try: agy, air, alma, ante, aside, astrbot, ...)
```

That is not a limitation to work around — it is the design. **The agent is the client,
magpie is the server.** For the ~60 agents magpie knows, one command does it:

```bash
magpie hermes group/cheap-first      # Hermes
magpie codex group/cheap-first       # Codex
magpie claude group/cheap-first      # Claude Code
magpie ls                            # what magpie sees on this machine
```

OpenClaw is the one that needs wiring by hand, because it has no OpenAI-compatible
server of its own (`/v1/models` and `/v1/chat/completions` on its gateway both 404).
This skill does that one job.

---

## Install

### One line — for any agent

Paste this into Claude Code, Hermes, OpenClaw, Codex, Cursor, or any agent that
supports skills:

```
npx -y skills@latest add MrFengcn/magpie-agent-bridge -g -a '*' -s '*' -y
```

The [skills CLI](https://www.npmjs.com/package/skills) detects which agents you run
and installs into each one's skills directory.

To install into one agent only:

```
npx -y skills@latest add MrFengcn/magpie-agent-bridge -g -a claude -y
```

### By hand

```bash
git clone https://github.com/MrFengcn/magpie-agent-bridge.git
cp -r magpie-agent-bridge ~/.hermes/skills/    # or ~/.claude/skills/, ~/.agents/skills/, …
```

---

## Use

```bash
# Is the gateway up, and is OpenClaw already wired?
python3 scripts/openclaw_magpie.py doctor

# What models are available?
python3 scripts/openclaw_magpie.py list

# Wire OpenClaw (writes the config, then validates it)
python3 scripts/openclaw_magpie.py install

# Restart the gateway — it must be stopped first
openclaw gateway stop --force && openclaw gateway start
curl -s http://127.0.0.1:18789/health     # startup takes 30–60s

# Prove it with a real turn
python3 scripts/openclaw_magpie.py verify

# Undo
python3 scripts/openclaw_magpie.py uninstall
```

`install` backs up `openclaw.json` to `openclaw.json.bak-openclaw-magpie`;
`uninstall` restores it.

---

## Pick the right model id

`GET /v1/models` returns three kinds of id, and choosing the wrong kind is the most
common mistake:

| Kind | Example | Use it? |
|---|---|---|
| Routing group | `group/cheap-first` | ✅ **Best.** Fails over between accounts automatically |
| Auto group | `auto/glm-5.3` | ✅ One logical model, several providers behind it |
| Bare provider model | `openrouter/openai/gpt-6.1-terra-pro` | ⚠️ The model part has slashes — ambiguous for `provider/model` |

A routing group is what magpie is for: when one account's quota runs out, the next
one takes over and the agent never sees an error.

---

## The four places a model must appear

Adding a provider is not enough. OpenClaw reads models from **four** places in
`~/.openclaw/openclaw.json`, and all four are required:

1. `models.providers.magpie.models[]`
2. `agents.defaults.models["magpie/<id>"] = {}`
3. `agents.defaults.modelPolicy.allow[]` ← **the sneaky one.** Miss it and the model
   stays invisible in the picker and the default silently reverts
4. `agents.defaults.model.primary` — only if it should become the default

The script handles all of them.

```json
"magpie": {
  "baseUrl": "http://127.0.0.1:3425/v1",
  "apiKey": "magpie",
  "api": "openai-completions",
  "timeoutSeconds": 180,
  "headers": { "User-Agent": "openclaw" },
  "models": [
    { "id": "group/cheap-first", "name": "cheap-first", "reasoning": true,
      "input": ["text", "image"], "contextWindow": 1048576, "maxTokens": 131072,
      "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 } }
  ]
}
```

---

## Keeping them in sync (automatic)

magpie's model list changes whenever you add a provider account, a plugin or a
routing group. Nothing pushes that into `openclaw.json` — so `install` alone leaves
you behind.

The sync script closes that loop:

```bash
python3 scripts/magpie_openclaw_sync.py --dry-run   # report only; exit 2 = would change
python3 scripts/magpie_openclaw_sync.py             # sync, restart gateway if changed
python3 scripts/magpie_openclaw_sync.py --no-restart
python3 scripts/magpie_openclaw_sync.py --force     # rewrite + restart even if unchanged
```

It does more than `install` does:

| | `install` | `sync` |
|---|---|---|
| adds models | ✅ | ✅ |
| removes models the gateway dropped | ❌ | ✅ |
| refreshes entries whose metadata changed | ❌ | ✅ |
| restarts the gateway | always | only when something changed |
| validates and rolls back on failure | ✅ | ✅ |

To install the automation — script, skill, launchd job and a Hermes cron task:

```bash
bash scripts/install-sync.sh      # --no-launchd / --dry-run / --no-restart
bash scripts/uninstall-sync.sh    # --with-wiring / --purge
```

The cron task runs every 30 minutes with `no_agent`, so it costs no LLM calls and
stays silent when there is nothing to do. On macOS the launchd job additionally
watches magpie's config directory, so a model change lands within seconds.

> The launchd job may fail to load with `! 加载失败` — Hermes blocks `launchctl`
> from inside its own gateway session. Run
> `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.walter.magpie-openclaw-sync.plist`
> from a plain shell, or rely on the cron task alone.

Log: `~/.hermes/logs/magpie-openclaw-sync.log`.

---

## Layout

```
magpie-agent-bridge/
├── SKILL.md                        # the skill itself
├── README.md
├── LICENSE                         # MIT
├── scripts/
│   ├── openclaw_magpie.py          # doctor / list / install / uninstall / verify
│   ├── magpie_openclaw_sync.py     # keep openclaw.json in step with the gateway
│   ├── install-sync.sh             # install the sync automation
│   └── uninstall-sync.sh           # remove it
├── tests/
│   ├── test_openclaw_magpie.py
│   └── test_magpie_openclaw_sync.py
├── references/
│   ├── platforms.md                # macOS / Windows / Linux specifics
│   └── magpie-openclaw-sync.plist.template   # macOS launchd job
└── .github/workflows/ci.yml
```

---

## Pitfalls

- **magpie must be running.** The gateway is served by the magpie app. If it quits,
  every OpenClaw request to it fails. `magpie autostart on` on macOS.
- **OpenClaw's gateway must be stopped before it will restart.** `gateway restart`
  refuses while it is running, and `doctor --fix` fails with a state-DB lock error.
- **Startup takes 30–60s.** `gateway start` may return before the listener is up.
  Check `curl -s http://127.0.0.1:18789/health`.
- **Never use a bare `provider/model` id with a slashy model part.** OpenClaw would
  mis-split `openrouter/openai/gpt-6.1`. Use `group/*` or `auto/*`.
- **A routing group is not a model.** `group/cheap-first` picks a *different*
  underlying model per account.
- **Cost reporting is meaningless here.** magpie's price depends on which upstream
  account served the call; the model entries use `cost: 0`.

---

## License

MIT — see [LICENSE](LICENSE).

magpie itself is a separate project by [yetone](https://github.com/yetone/magpie),
also MIT. This skill is not affiliated with or endorsed by it.
