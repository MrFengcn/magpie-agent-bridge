---
name: openclaw-magpie
description: "Use when wiring OpenClaw to magpie's local gateway."
version: 2.1.0
author: Walter (MrFengcn)
license: MIT
tags: [magpie, openclaw, gateway, llm, provider, model-router]
related_skills: [openclaw-configuration, skill-publishing]
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

**The installed directory is named after the frontmatter `name:` (`openclaw-magpie`),
not the repository (`magpie-agent-bridge`).** Look in
`~/.agents/skills/openclaw-magpie/` when verifying an install.

To forward to someone else, give them natural language naming the method, the
skill and the problem — see the `skill-publishing` skill for the shape:

```
请通过 npx -y skills@latest add MrFengcn/magpie-agent-bridge -g -a '*' -s '*' -y 的方式安装 openclaw-magpie 技能，来帮我解决 magpie 原生不支持 OpenClaw、导致 OpenClaw 无法使用 magpie 模型和路由组的问题。
```

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

The trace lives under **`result.meta.executionTrace`** in the JSON output — not at
the top level and not directly under `result`. Parsing the wrong path yields
`None` and a false "did not use magpie" verdict. The provider is also readable
from `result.meta.agentMeta.provider` / `.model` as a fallback.

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

## Keeping the two in sync

magpie's model list changes whenever you add a provider account, a plugin or a
routing group. Nothing pushes that into `openclaw.json` — a second sync has to run:

```bash
python3 scripts/magpie_openclaw_sync.py             # sync if needed, restart if changed
python3 scripts/magpie_openclaw_sync.py --dry-run   # report only; exit 2 when it would change something
python3 scripts/magpie_openclaw_sync.py --no-restart
python3 scripts/magpie_openclaw_sync.py --force     # rewrite + restart even when nothing changed
```

It writes the same four places as `install`, but it also:

- **removes** `magpie/*` refs whose model id the gateway no longer serves at all (an
  id that merely stopped being a group/auto is left alone)
- **refreshes** entries whose metadata drifted (same id, new context window or
  display name) — comparing ids alone would leave stale metadata behind forever
- backs up per run to `openclaw.json.bak-magpie-sync`, runs `openclaw config validate`
  and **rolls back** on failure
- restarts the gateway **only when something actually changed**

It never touches `agents.defaults.model.primary` — if a removal invalidates the
primary it says so and leaves the decision to you.

To install the automation (script + skill + launchd + Hermes cron):

```bash
bash scripts/install-sync.sh            # add --no-launchd / --dry-run / --no-restart
bash scripts/uninstall-sync.sh          # add --with-wiring / --purge
```

Scheduled two ways, both idempotent and cheap when nothing changed:

- **Hermes cron** `magpie→OpenClaw 模型同步` — `no_agent: true`, every 30m, script
  `magpie_openclaw_sync.py` (relative paths resolve under `~/.hermes/scripts/`).
  `no_agent` means no LLM per tick: stdout is delivered verbatim and **empty stdout
  sends nothing**, so the script prints to stdout only for real changes and
  actionable failures; the routine "up to date" line is file-only.
- **launchd** `~/Library/LaunchAgents/com.walter.magpie-openclaw-sync.plist` —
  WatchPaths on `~/.config/magpie`, `providers.json` and `plugin-providers.json`
  (magpie persists its catalog there, so a change there means the model list
  probably moved) plus `StartInterval` 1800 as a backstop. **Not loaded by default:**
  the Hermes gateway blocks `launchctl bootstrap`/`submit`, so load it from a plain
  shell —
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.walter.magpie-openclaw-sync.plist`

Log: `~/.hermes/logs/magpie-openclaw-sync.log`.

`references/sync-automation.md` has the long version: what each scheduling path does,
the guardrails, the log files and a troubleshooting table.

Two guardrails worth copying: the script refuses to write when the gateway serves
fewer than 5 group/auto models (magpie is mid-restart with a half-loaded catalog —
syncing then would gut the config), and "magpie unreachable" exits 0 silently
(magpie being off is a normal state, not a failure to alert on every 30 minutes).

## Pitfalls

- **magpie must be running.** The gateway is served by the magpie app. If magpie
  quits, every OpenClaw request to it fails. On macOS: `magpie autostart on`.
- **OpenClaw's gateway must be stopped before it will restart.** `gateway restart`
  refuses while it is running, and `doctor --fix` fails with a state-DB lock
  error. Use `gateway stop --force && gateway start`.
- **Startup takes 30–60s.** `gateway start` may return before the listener is up.
  Verify with `curl -s http://127.0.0.1:18789/health`, not the command's exit code.
- **`agents.defaults.model` exists in two shapes.** Hand edits and older configs
  keep an object with a `primary` key; OpenClaw's own gateway rewrites it to the
  bare model-ref string when the default model is changed out of band (observed
  2026-10-27 15:40:37: `model` became magpie/group/cheap-first while its `.bak`
  still held the object form). Read it defensively with an isinstance check, or
  `doctor` dies with 'str object has no attribute get' the next time you switch a
  model in the dashboard.
- **Never use a bare `provider/model` id with a slashy model part.** OpenClaw
  would mis-split `openrouter/openai/gpt-6.1`. Use `group/*` or `auto/*`.
- **A routing group is not a model.** `group/cheap-first` picks a *different
  underlying model per account*. If you need one specific model, name it or use an
  `auto/*` group.
- **Cost reporting is meaningless here.** magpie's price depends on which upstream
  account served the call; the model entries use `cost: 0`.
- **`maxTokens` must be capped.** magpie advertises up to 524288 output tokens;
  OpenClaw's own ceiling is lower, so cap at 131072.
- **magpie identifies the caller by User-Agent**, so OpenClaw's requests are logged as
  `agent=openclaw` in `~/.config/magpie/usage.jsonl` even though magpie has no
  OpenClaw agent. Use that log to confirm traffic is actually flowing.
- **Don't paste real keys into the skill or a repo.** The gateway key is literally
  `magpie`; upstream keys live in magpie, not in OpenClaw's config.
- **Test the install against a config copy, not the live file.** Point
  `OPENCLAW_CONFIG_PATH` at a copy so a bad run cannot damage the real setup.
