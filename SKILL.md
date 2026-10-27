---
name: openclaw-magpie
description: "Use when wiring OpenClaw to magpie's local gateway."
version: 2.0.0
author: Walter (MrFengcn)
license: MIT
tags: [magpie, openclaw, gateway, llm, provider, model-router]
related_skills: [openclaw-configuration]
---

# OpenClaw → magpie gateway

magpie natively drives Hermes, Codex, Claude Code, Qwen Code, OpenCode, dsh and ~60
other agents — **but not OpenClaw**. This skill is the bridge for that one gap.

## When to Use

- The user wants OpenClaw to use magpie's models, routing groups or subscription accounts
- A magpie routing group should back an OpenClaw model
- magpie's quota failover should cover OpenClaw
- The user asks why magpie doesn't list OpenClaw, or how to make it work

## The one thing to understand

**magpie's agent list is compiled into its Go binary**, and its plugin mechanism
extends *providers*, not agents. So magpie will never list OpenClaw:

```
$ magpie openclaw
magpie: unknown agent "openclaw" (try: agy, air, alma, ante, aside, astrbot, ...)
```

This is not a bug to work around — it is the design. magpie is a **gateway**, and
the agent is its **client**. OpenClaw has no OpenAI-compatible server of its own
(`/v1/models` and `/v1/chat/completions` on its gateway both 404), so OpenClaw
must be pointed at magpie's gateway.

For every agent magpie *does* know, use its CLI — it edits that agent's config
format properly, preserving comments and ordering:

```bash
magpie ls                            # what magpie sees on this machine
magpie hermes group/cheap-first      # Hermes
magpie codex group/cheap-first       # Codex
magpie claude group/cheap-first      # Claude Code
magpie <agent> default               # take magpie out, restore what was there
```

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

## Quick start

```bash
# 1. Is the gateway up, and is OpenClaw already wired?
python3 scripts/openclaw_magpie.py doctor

# 2. What models are available?
python3 scripts/openclaw_magpie.py list

# 3. Wire OpenClaw (writes the config, then validates it)
python3 scripts/openclaw_magpie.py install

# 4. Restart the gateway — it must be stopped first
openclaw gateway stop --force && openclaw gateway start
curl -s http://127.0.0.1:18789/health     # startup takes 30–60s

# 5. Prove it with a real turn
python3 scripts/openclaw_magpie.py verify
```

`install` backs up `openclaw.json` to `openclaw.json.bak-openclaw-magpie` and
`uninstall` restores it.

## What magpie's gateway speaks

`http://127.0.0.1:3425` — the key is the literal word `magpie`.

| Endpoint | Protocol |
|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions |
| `POST /v1/responses` | OpenAI Responses |
| `POST /v1/messages` | Anthropic Messages |
| `GET /v1/models` | model catalog |

## Choose the right model id

`GET /v1/models` returns three kinds of id:

| Kind | Example | Use it? |
|---|---|---|
| Routing group | `group/cheap-first` | ✅ **Best.** Fails over between accounts automatically |
| Auto group | `auto/glm-5.3` | ✅ One logical model, several providers behind it |
| Bare provider model | `openrouter/openai/gpt-6.1-terra-pro` | ⚠️ The model part has slashes — ambiguous for `provider/model` |

**Prefer groups.** They are what magpie is for: when one account's quota runs out,
the next one takes over and the agent never sees an error. A bare model id has no
failover.

## The four places a model must appear

Adding a provider is not enough. OpenClaw reads models from **four** places in
`~/.openclaw/openclaw.json`, and all four are required:

1. `models.providers.magpie.models[]` — the provider entry itself
2. `agents.defaults.models["magpie/<id>"] = {}` — the registry
3. `agents.defaults.modelPolicy.allow[]` ← **the sneaky one.** Miss it and the
   model stays invisible in the picker and the default silently reverts, even
   though 1, 2 and 4 are all correct
4. `agents.defaults.model.primary` — only if it should become the default

The script handles all of them. Doing it by hand:

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

`api` must be `openai-completions` (maps to `/v1/chat/completions`). Valid values
are strictly `openai-completions`, `openai-responses`, `openai-chatgpt-responses`,
`anthropic-messages`, `google-generative-ai`, `google-vertex`, `github-copilot`,
`bedrock-converse-stream`, `ollama`, `pi-messages`, `azure-openai-responses`.
An invalid value crashes the gateway silently (exit code 7, empty health response).

## Verify it worked

```bash
openclaw agent --session-key "agent:main:test" --message "say OK" \
  --model "magpie/group/cheap-first" --json
```

Expect `"winnerProvider": "magpie"` and `"winnerModel": "group/cheap-first"`.
The trace lives under `result.meta.executionTrace` in the JSON output.

OpenClaw parses model refs with `indexOf("/")` — first slash only — so
`magpie/group/cheap-first` resolves to provider `magpie` + model
`group/cheap-first` correctly. Model ids containing slashes are fine.

## Platform differences

| | macOS | Windows | Linux |
|---|---|---|---|
| OpenClaw config | `~/.openclaw/openclaw.json` | same (`%USERPROFILE%\.openclaw\`) | same (`$HOME/.openclaw/`) |
| magpie binary | `/Applications/magpie.app/Contents/MacOS/magpie` | `%LOCALAPPDATA%\magpie\magpie.exe` | `~/.local/bin/magpie` |
| Gateway health | `http://127.0.0.1:18789/health` | same | same |

`OPENCLAW_CONFIG_PATH` overrides the config location — the script honours it,
which is how it can be tested against a copy without touching the live config.

## Pitfalls

- **magpie must be running.** The gateway is served by the magpie app. If magpie
  quits, every OpenClaw request to it fails. On macOS: `magpie autostart on`.
- **OpenClaw's gateway must be stopped before it will restart.** `gateway restart`
  refuses while it is running, and `doctor --fix` fails with a state-DB lock
  error. Use `gateway stop --force && gateway start`.
- **Startup takes 30–60s.** `gateway start` may return before the listener is up.
  Verify with `curl -s http://127.0.0.1:18789/health`, not the command's exit code.
- **Never use a bare `provider/model` id with a slashy model part.** OpenClaw
  would mis-split `openrouter/openai/gpt-6.1`. Use `group/*` or `auto/*`.
- **A routing group is not a model.** `group/cheap-first` picks a *different
  underlying model per account*. If you need one specific model, name it or use an
  `auto/*` group.
- **Cost reporting is meaningless here.** magpie's price depends on which upstream
  account served the call; the model entries use `cost: 0`.
- **`maxTokens` must be capped.** magpie advertises up to 524288 output tokens;
  OpenClaw's own ceiling is lower, so cap at 131072.
- **Don't paste real keys into the skill or a repo.** The gateway key is literally
  `magpie`; upstream keys live in magpie, not in OpenClaw's config.
