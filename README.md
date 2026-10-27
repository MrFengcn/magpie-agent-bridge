# magpie-agent-bridge

**One gateway, every agent.** Point OpenClaw, Hermes, Codex, Claude Code, Gemini CLI,
Qwen Code, OpenCode, Droid, Cline, Zed, Cursor CLI, Goose, Kimi Code and any other
agent CLI at [magpie](https://usemagpie.ai)'s local gateway — so one account pool and
one routing layer serve all of them.

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
magpie is the server.** For the ~64 agents magpie knows (Claude Code, Codex, Gemini
CLI, Hermes, Qwen Code, OpenCode, dsh, Zed, Cursor CLI, Goose, Kimi Code, Droid,
Cline, WorkBuddy, Raycast, VS Code Chat, Copilot CLI, …) use magpie's own CLI, which
edits each agent's config format properly. For everything else — OpenClaw included —
point it at the gateway yourself.

---

## Install

### As a skill

Drop the folder into your agent's skills directory:

```bash
# Hermes / Claude Code / OpenClaw style
cp -r magpie-agent-bridge ~/.hermes/skills/

# or symlink
ln -s ~/path/to/magpie-agent-bridge ~/.hermes/skills/magpie-agent-bridge
```

### As a standalone tool

```bash
git clone https://github.com/MrFengcn/magpie-agent-bridge.git
cd magpie-agent-bridge
python3 scripts/magpie_bridge.py doctor
```

Requirements: Python 3.9+ and magpie running (`magpie autostart on` on macOS keeps it
up at login).

---

## Use

```bash
# Check the gateway and list every agent on this machine
python3 scripts/magpie_bridge.py doctor

# What models are available?
python3 scripts/magpie_bridge.py list

# Point agents at the gateway
python3 scripts/magpie_bridge.py install claude
python3 scripts/magpie_bridge.py install openclaw hermes codex

# Prove it works end to end
python3 scripts/magpie_bridge.py verify --model group/cheap-first

# Look at one agent
python3 scripts/magpie_bridge.py show hermes

# Undo
python3 scripts/magpie_bridge.py uninstall hermes
```

### Or use magpie's own CLI

For every agent magpie knows, its CLI is better — it edits the agent's own config
format and preserves comments and ordering:

```bash
magpie ls                              # what magpie sees on this machine
magpie claude group/cheap-first       # Claude Code on the routing group
magpie codex group/cheap-first        # Codex
magpie hermes group/cheap-first       # Hermes
magpie <agent> default                # take magpie out, restore what was there
```

### Or just export two variables

Works with almost anything, and touches no config file:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:3425/v1     OPENAI_API_KEY=magpie
export ANTHROPIC_BASE_URL=http://127.0.0.1:3425     ANTHROPIC_API_KEY=magpie
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:3425 GEMINI_API_KEY=magpie
```

---

## Pick the right model id

`GET /v1/models` returns three kinds of id, and choosing the wrong kind is the most
common mistake:

| Kind | Example | Use it? |
|---|---|---|
| Routing group | `group/cheap-first` | ✅ **Best.** Fails over between accounts automatically |
| Auto group | `auto/glm-5.3` | ✅ One logical model, several providers behind it |
| Bare provider model | `openrouter/openai/gpt-6.1-terra-pro` | ⚠️ The model part has slashes — ambiguous for `provider/model` agents |

A routing group is what magpie is for: when one account's quota runs out, the next
one takes over and the agent never sees an error.

---

## OpenClaw, specifically

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
    { "id": "group/cheap-first", "name": "cheap-first", "reasoning": true,
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

```bash
openclaw config validate
openclaw gateway stop --force && openclaw gateway start
curl -s http://127.0.0.1:18789/health     # startup takes 30–60s

openclaw agent --session-key "agent:main:test" --message "say OK" \
  --model "magpie/group/cheap-first" --json
# expect "winnerProvider": "magpie", "winnerModel": "group/cheap-first"
```

OpenClaw parses model refs with `indexOf("/")` — first slash only — so
`magpie/group/cheap-first` resolves to provider `magpie` + model `group/cheap-first`
correctly.

---

## Layout

```
magpie-agent-bridge/
├── SKILL.md                        # the skill itself
├── README.md
├── LICENSE                         # MIT
├── scripts/
│   └── magpie_bridge.py            # cross-platform installer / doctor / verifier
└── references/
    ├── agent-catalog.md            # all 64 agents: config file + managed fields
    └── platforms.md                # macOS / Windows / Linux paths and differences
```

---

## Pitfalls

- **magpie must be running.** The gateway is served by the magpie app. If it quits,
  every agent pointed at it fails. `magpie autostart on` on macOS.
- **Never use a bare `provider/model` id with a slashy model part.** Agents that
  address models as `provider/model` will mis-split `openrouter/openai/gpt-6.1`.
  Use `group/*` or `auto/*`.
- **A routing group is not a model.** `group/cheap-first` picks a *different*
  underlying model per account. If you need one specific model, name it or use an
  `auto/*` group.
- **Back up before editing.** The bridge writes `<file>.magpie-bridge-bak` next to
  the config; `uninstall` restores it.
- **Restart the agent after a config change.** Most agents read their config at
  start-up, not per request.
- **Cost reporting is meaningless for these models.** magpie's price depends on which
  upstream account served the call; the bridge writes `cost: 0`.
- **OpenClaw needs the gateway stopped before it will restart.** `gateway restart`
  refuses while it is running, and `doctor --fix` fails with a state-DB lock error.

---

## License

MIT — see [LICENSE](LICENSE).

magpie itself is a separate project by [yetone](https://github.com/yetone/magpie),
also MIT. This skill is not affiliated with or endorsed by it.
