---
name: magpie-agent-bridge
description: "Use when routing any AI agent CLI through magpie's local gateway."
version: 1.0.0
author: Walter (MrFengcn)
license: MIT
tags: [magpie, gateway, agents, openclaw, hermes, codex, claude, gemini, providers]
related_skills: [openclaw-configuration, github-workflow]
---

# magpie-agent-bridge

Point **any** AI agent CLI at [magpie](https://usemagpie.ai)'s local gateway, so one
account pool and one routing layer serve every agent on the machine.

Works on **macOS, Windows and Linux** with only Python 3.9+ (standard library only).

## When to Use

- The user wants an agent (OpenClaw, Hermes, Codex, Claude Code, Gemini CLI, Qwen Code,
  OpenCode, Droid, Cline, Kimi Code, Zed, Cursor CLI, Goose, …) to use magpie's models
- A magpie routing group should back an agent's model
- magpie's quota failover should cover an agent the user runs daily
- The user wants one provider across many agents instead of a key per agent

## The one thing to understand first

**magpie does not have an "OpenClaw" agent, and it will never add one** — its agent
list is compiled into the Go binary and its plugin mechanism extends *providers*, not
agents. There are two integration directions, and only one works:

| Direction | Works? | Why |
|---|---|---|
| agent → magpie gateway | ✅ | Any agent that accepts a base URL can point at the gateway |
| magpie → agent (as an agent) | ❌ for OpenClaw | The agent list is compiled in; `magpie openclaw` → `unknown agent` |

**So: the agent is the client, magpie is the server.** This is by design — magpie's
README says "Anything else that takes a base URL can use the gateway too."

For the ~64 agents magpie *does* know (Claude Code, Codex, Gemini CLI, Hermes, Qwen
Code, OpenCode, dsh, Zed, Cursor CLI, Goose, Kimi Code, Droid, Cline, WorkBuddy,
Raycast, VS Code Chat, Copilot CLI, …), use magpie's own CLI — it edits each agent's
config format correctly, preserving comments and ordering. For everything else,
write the provider block yourself; the gateway speaks four API dialects, so most
agents fit.

## Install

One line, for any agent on the machine:

```bash
npx -y skills@latest add MrFengcn/magpie-agent-bridge -g -a '*' -s '*' -y
```

The [skills CLI](https://www.npmjs.com/package/skills) detects which agents are
installed and copies the skill into each one's skills directory. One agent only:
`-a claude` instead of `-a '*'`.

By hand: clone the repo and copy it into the agent's skills directory
(`~/.hermes/skills/`, `~/.claude/skills/`, `~/.agents/skills/`, `~/.codex/skills/`).

As a standalone tool, no skill install needed:

```bash
git clone https://github.com/MrFengcn/magpie-agent-bridge.git
cd magpie-agent-bridge
python3 scripts/magpie_bridge.py doctor
```

Requirements: Python 3.9+ and magpie running (`magpie autostart on` on macOS keeps it
up at login).

## Quick start

```bash
# 1. Is the gateway up? (magpie serves it while running)
python3 scripts/magpie_bridge.py doctor

# 2. What models are available?
python3 scripts/magpie_bridge.py list

# 3. Point an agent at it
python3 scripts/magpie_bridge.py install claude
python3 scripts/magpie_bridge.py install openclaw hermes codex

# 4. Prove it works end to end
python3 scripts/magpie_bridge.py verify --model group/cheap-first
```

`doctor` prints every agent it can find on this machine, so it doubles as a
discovery tool.

## What magpie's gateway speaks

`http://127.0.0.1:3425` — API key `magpie` (any token works from localhost).

| Endpoint | Protocol |
|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions |
| `POST /v1/responses` | OpenAI Responses |
| `POST /v1/messages` | Anthropic Messages |
| `GET /v1/models` | model catalog |
| `POST /v1/images/generations`, `/v1/videos`, `/v1/embeddings`, `/v1/rerank`, `/v1/audio/*` | extras |

For any agent that takes a base URL, set:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:3425/v1     OPENAI_API_KEY=magpie
export ANTHROPIC_BASE_URL=http://127.0.0.1:3425    ANTHROPIC_API_KEY=magpie
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:3425 GEMINI_API_KEY=magpie
```

That covers most agents without touching a config file at all.

## Choose the right model id

`GET /v1/models` returns three kinds of id, and picking the wrong kind is the most
common mistake:

| Kind | Example | Use it? |
|---|---|---|
| Routing group | `group/cheap-first` | ✅ **Best.** Fails over between accounts/providers automatically |
| Auto group | `auto/glm-5.3` | ✅ One logical model, several providers behind it |
| Bare provider model | `openrouter/openai/gpt-6.1-terra-pro` | ⚠️ The model part contains slashes — ambiguous for agents that address models as `provider/model` |

**Prefer groups.** They are what magpie is for: when one account's quota runs out,
the next one takes over and the agent never sees an error. A bare model id has no
failover.

## Agent-specific notes

### OpenClaw (not a magpie agent — wire it by hand)

OpenClaw has no OpenAI-compatible server of its own (`/v1/models` and
`/v1/chat/completions` on its gateway both 404), so it must be a *client* of the
magpie gateway. Add a provider to `~/.openclaw/openclaw.json`:

```json
"magpie": {
  "baseUrl": "http://127.0.0.1:3425/v1",
  "apiKey": "magpie",
  "api": "openai-completions",
  "timeoutSeconds": 180,
  "headers": { "User-Agent": "openclaw" },
  "models": [
    { "id": "group/cheap-first", "name": "便宜优先", "reasoning": true,
      "input": ["text", "image"], "contextWindow": 1048576, "maxTokens": 131072,
      "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 } }
  ]
}
```

Then sync **four** places in the same file — all four are required:

1. `models.providers.magpie.models[]`
2. `agents.defaults.models["magpie/<id>"] = {}`
3. `agents.defaults.modelPolicy.allow[]` ← **the sneaky one.** Miss it and the model
   stays invisible in the picker and the default silently reverts
4. `agents.defaults.model.primary` — only if it should become the default

Validate, then restart the gateway with the gateway stopped first:

```bash
openclaw config validate
openclaw gateway stop --force && openclaw gateway start
curl -s http://127.0.0.1:18789/health     # startup takes 30–60s
```

Verify with a real turn:

```bash
openclaw agent --session-key "agent:main:test" --message "say OK" \
  --model "magpie/group/cheap-first" --json
# expect "winnerProvider": "magpie", "winnerModel": "group/cheap-first"
```

OpenClaw parses model refs with `indexOf("/")` — first slash only — so
`magpie/group/cheap-first` resolves to provider `magpie` + model `group/cheap-first`
correctly. Model ids with slashes are fine.

### Codex

`~/.codex/config.toml`. magpie drives it natively:

```bash
magpie codex group/cheap-first
```

### Claude Code

`~/.claude/settings.json`. magpie drives it natively:

```bash
magpie claude group/cheap-first
```

This makes Claude Code send Anthropic Messages to the gateway. Claude Code also
accepts plain env vars, which is the least invasive route:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:3425
export ANTHROPIC_API_KEY=magpie
```

### Hermes Agent

`~/.hermes/config.yaml` (Windows: `%LOCALAPPDATA%\hermes\config.yaml`;
`$HERMES_HOME` overrides both). magpie drives it natively:

```bash
magpie hermes group/cheap-first
```

### Gemini CLI

`~/.gemini/settings.json` + `~/.gemini/.env`:

```
GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:3425
GEMINI_API_KEY=magpie
```

### Qwen Code

`~/.qwen/settings.json` — magpie's models become `modelProviders.openai` entries on
a `MAGPIE_QWEN_API_KEY` env var, and `security.auth.selectedType` must be `openai`
while wired.

### OpenCode

`~/.config/opencode/opencode.json` (`$OPENCODE_CONFIG_DIR` overrides). Provider-scoped
agents take `provider/model`.

### DeepSeek Harness (dsh)

`~/.dsh/profiles/*/cordis.patch.yml`; the key is `MAGPIE_GATEWAY_KEY` in `~/.dsh/.env`.

### Zed / VS Code Chat / Cursor CLI / Raycast / Copilot CLI

See `references/agents.md` for the exact file and field per agent.

## Platform differences

`references/platforms.md` has the per-OS config paths. The short version:

| | macOS | Windows | Linux |
|---|---|---|---|
| XDG config | `~/.config` | `%APPDATA%` | `~/.config` (or `$XDG_CONFIG_HOME`) |
| VS Code | `~/Library/Application Support/Code/User` | `%APPDATA%\Code\User` | `~/.config/Code/User` |
| Hermes | `~/.hermes` | `%LOCALAPPDATA%\hermes` | `$HERMES_HOME` or `~/.hermes` |
| magpie binary | `/Applications/magpie.app/Contents/MacOS/magpie` | `%LOCALAPPDATA%\magpie\magpie.exe` | `~/.local/bin/magpie` |

## Pitfalls

- **magpie must be running.** The gateway is served by the magpie app. If magpie
  quits, every agent pointed at it fails. On macOS: `magpie autostart on`.
- **Never use a bare `provider/model` id with a slashy model part.** Agents that
  address models as `provider/model` will mis-split `openrouter/openai/gpt-6.1`.
  Use `group/*` or `auto/*` instead.
- **A routing group is not a model.** `group/cheap-first` picks a *different
  underlying model per account*. If you need a specific model, name it or use an
  `auto/*` group.
- **Back up before editing.** The bridge writes `<file>.magpie-bridge-bak` next to
  the config; `magpie-bridge uninstall <agent>` restores it.
- **Restart the agent after a config change.** Most agents read their config at
  start-up, not per request. Claude Desktop and JetBrains plugins are the worst
  offenders.
- **Cost reporting is meaningless for these models.** magpie's price depends on
  which upstream account served the call; the bridge writes `cost: 0`.
- **OpenClaw needs the gateway stopped before it will restart** — `gateway restart`
  refuses while it is running, and `doctor --fix` fails with a state-DB lock error.
- **Don't paste real keys into the skill or a repo.** The gateway key is literally
  `magpie`; upstream keys live in magpie, not in the agent configs.
