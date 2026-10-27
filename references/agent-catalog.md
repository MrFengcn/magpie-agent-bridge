# Agent reference

Every agent magpie can drive natively, with its config file and the fields magpie
manages. magpie's own agent list is compiled into the binary — `magpie openclaw`
prints the live list and the error message:

```
magpie: unknown agent "openclaw" (try: agy, air, alma, ante, aside, astrbot, atomcode,
cindy, claude, claude-desktop, claude-science, cline, codebuddy, codex, commandcode,
copilot, copilot-jetbrains, crush, cursor, cursor-local, deveco, devin, droid, dsh,
empryo, fx, gemini, goose, grok, grok-app, hanako, hermes, jcode, kimi, lody, mimocode,
minimax-code, morph, mothx, muse, omo, omp, openchamber, opencode, openpencil, pencil,
pi, prime-agent, qoder, qoder-cn, qwen, raycast, reasonix, snow, stepcode, t3code,
vscode, vscode-insiders, vscodium, workbuddy, workbuddy-ai, zcode, zed, zoo-code)
```

The list changes between magpie releases — read it from the binary rather than
trusting this table.

## The two ways to drive an agent

**1. magpie's CLI (preferred).** It knows each agent's config format and edits only
the one key that matters, preserving comments, ordering and indentation:

```bash
magpie claude group/cheap-first       # Claude Code on the routing group
magpie codex group/cheap-first        # Codex on the routing group
magpie hermes group/cheap-first       # Hermes on the routing group
magpie qwen group/cheap-first         # Qwen Code
magpie opencode group/cheap-first     # OpenCode
magpie <agent> default                # take magpie out, restore what was there
magpie <agent> <field> default        # restore just one field
```

Use `magpie ls` to see which agents are installed and what each is set to.

**2. Env vars (works with almost anything).** magpie's README documents this
explicitly — no config file is touched:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:3425/v1     OPENAI_API_KEY=magpie
export ANTHROPIC_BASE_URL=http://127.0.0.1:3425     ANTHROPIC_API_KEY=magpie
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:3425 GEMINI_API_KEY=magpie
```

## Config files and managed fields

Paths are macOS-style; see `platforms.md` for Windows and Linux.

| Agent | Config file | Fields magpie manages |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | provider, model, opus/sonnet/haiku/fable, auto mode, sign-in through magpie |
| Claude Desktop | `~/Library/Application Support/Claude/` + `Claude-3p/configLibrary/` | provider (third-party gateway mode), opus/sonnet/haiku/fable, subagent model and effort |
| Claude Science | same as Claude Code | model |
| Codex | `~/.codex/config.toml` | provider, model, effort |
| Gemini CLI | `~/.gemini/settings.json`, `~/.gemini/.env` | auth, model |
| OpenCode | `~/.config/opencode/opencode.json(c)` (`$OPENCODE_CONFIG_DIR`) | model, small |
| OpenChamber | `~/.config/openchamber/preferences.json` | model, small |
| MiMo Code | `~/.config/mimocode/mimocode.json(c)` | model, small |
| DevEco Code | `~/.config/deveco/deveco.json(c)` | model, small |
| Pi | `~/.pi/agent/settings.json` | model |
| StepCode | `~/.stepcode/config.toml` + `models.json` | model |
| MothX | `~/.mothx/settings.json` | model, thinking level |
| Aside | `~/.aside/u/0/settings.json` | model, effort, fast/standard/deep, visual, image |
| OmO | `~/.omo/agent/settings.json` | model |
| Prime Agent | `~/.prime/agent/settings.json` | model, thinking |
| Goose | `~/.config/goose/config.yaml` | model |
| Cursor CLI | `~/.cursor/cli-config.json` | model |
| Zed | `~/.config/zed/settings.json` | model (a `magpie` OpenAI-compatible provider) |
| VS Code Chat | `~/Library/Application Support/Code/User/settings.json` + `chatLanguageModels.json` | model (`chat.defaultModel`) |
| VS Code Insiders | same under `Code - Insiders/User` | as VS Code, its own row |
| VSCodium Chat | same under `VSCodium/User` | as VS Code |
| Zoo Code | VS Code's `Code/User/settings.json` (import path in `globalStorage`) | model |
| Copilot (JetBrains) | `~/.config/github-copilot/byok.json` | provider (a `magpie` custom endpoint) |
| JetBrains Air | `~/Library/Application Support/JetBrains/Air/acp.json` | model (a `Magpie` ACP agent) |
| Copilot CLI | `~/.copilot/settings.json` | model |
| Crush | `~/.config/crush/crush.json` | large, small |
| DeepSeek Harness (dsh) | `~/.dsh/profiles/*/cordis.patch.yml` | model, effort |
| Reasonix Studio | `~/.reasonix/config.toml` + `.env` | model (Executor), planner, effort |
| Command Code | `~/.commandcode/settings.json` | model |
| fx | `~/.fx/settings.json` | model |
| omp (oh-my-pi) | `~/.omp/agent/config.yml` + `models.yml` | model |
| Devin | `~/.config/devin/config.json` | model |
| **Hermes Agent** | `~/.hermes/config.yaml` | model |
| Mister Morph | `~/.morph/config.yaml` | model, effort |
| Kimi Code | `~/.kimi/config.toml` | model |
| Qwen Code | `~/.qwen/settings.json` | model |
| Muse Code | `~/.config/muse/settings.json` | model |
| Empryo | `~/.empryo/config.json` | defaultModel |
| Ante | `~/.ante/catalog.json` + `settings.json` | provider, model |
| AstrBot | `~/.astrbot/data/cmd_config.json` | model |
| jcode | `~/.jcode/config.toml` | model |
| MiniMax Code | `~/.minimax/config.yaml` | model |
| Droid (Factory) | `~/.factory/settings.json` | model |
| Cline CLI | `~/.cline/data/settings/providers.json` | model, effort |
| Qoder CLI | `~/.qoder/settings.json` | model, effort |
| Qoder CN CLI | `~/.qoder-cn/settings.json` | model, effort |
| Grok Build | `~/.grok/config.toml` | model, effort |
| Grok App | `~/Library/Application Support/com.grokapp.grok-app/agent-home/config.toml` | provider, model |
| ZCode | `~/.zcode/v2/provider_config.json` | provider |
| WorkBuddy | `~/.workbuddy/models.json` | provider |
| WorkBuddy AI | `~/.workbuddy-ai/models.json` | provider |
| CodeBuddy Code | `~/.codebuddy/models.json` | model |
| Raycast | `~/.config/raycast/ai/providers.yaml` | provider |
| Kiro Crew | `~/.kiro/crew/config.json` | provider, harness |
| OpenPencil | `~/Library/Application Support/openpencil/settings.json` | provider |
| T3 Code | `~/.t3/userdata/settings.json` | provider |
| OpenHanako | `~/.hanako/provider-catalog.json` + `agents/<id>/config.yaml` | model |
| AtomCode | `~/.atomcode/config.toml` | model, effort |
| Snow CLI | `~/.snow/profiles/magpie.json` | model |
| Alma | Alma's local API (`localhost:23001`) | model |
| Lody | its own import dialog | adds selected providers |

## Agent-scoped models

Provider-scoped agents address models as `provider/model`: OpenCode, MiMo Code,
DevEco Code, Pi, OmO, StepCode, MothX, Aside, Goose, Crush, omp, Hermes Agent.

Inside magpie's catalog, a routing group is `group/<id>` and an auto group is
`auto/<id>`. When an agent expects `provider/model`, magpie supplies the `magpie`
provider itself, so the agent sees `magpie/group/cheap-first`.

## Notes on specific agents

**Hermes** — `~/.hermes/config.yaml`; on Windows `%LOCALAPPDATA%\hermes\config.yaml`.
Each Hermes profile under `profiles/` gets its own copy. magpie's Hermes integration
writes a `magpie` provider pointing at the gateway with `api_mode: chat_completions`.

**dsh** — the key is `MAGPIE_GATEWAY_KEY` in `~/.dsh/.env`, plus dsh's own key store
`~/.dsh/.credentials.yaml`. On one of magpie's models, dsh's `web-search-deepseek`
row also goes through the gateway, which searches with the model.

**Claude Desktop** — a packaged Desktop on Windows keeps its config in
`%LOCALAPPDATA%\Packages\Claude_<publisher>\LocalCache\Local`, and Desktop 2.31226+
reads the real `%LOCALAPPDATA%\Claude-3p` instead — magpie writes both.

**VS Code Chat** — needs VS Code 1.122+, and its Chat features must be turned on
(`chat.disableAIFeatures=false`, `defaultChatAgent`, `trustedExtensionAuthAccess`).
No Copilot sign-in or key is needed. With Marketplace Copilot Chat 0.48.1, which has no
Custom Endpoint provider, the group is written for its OpenAI Compatible provider
instead (token sent as `x-api-key`).

**Copilot (JetBrains)** — found through the `github-copilot-intellij` plugin in a
JetBrains IDE or Android Studio. Listed after the IDE restarts, and only while
Copilot is signed in on a plan with BYOK.

**JetBrains Air** — magpie's provider is exposed as a `Magpie` ACP agent running
`opencode acp`, so Air's model menu lists magpie's models and routing groups. Needs
OpenCode installed.

**Lody** — adds selected Claude, Codex, Pi, DSH, Kimi Code, Grok and Bub providers on
the local machine through its own confirmation dialog. magpie edits no settings here.

**Grok App** — the route (`[models] default`) stays on the App's own route until the
user presses Use on magpie there; Disconnect drops the channel and restores the
previous route only if it is still `magpie`.

**Snow CLI** — magpie writes `~/.snow/profiles/magpie.json`, makes it the active
profile and copies it to `config.json`. The Snow App takes the profile in with
"Sync Snow CLI API config".

## magpie's plugin mechanism

`magpie plugin add <npm | git | path>` installs an OpenCode provider plugin, a pi
package, or a gateway hook/middleware. This extends **providers and the gateway** —
it does **not** add new agents. Use it for a provider magpie doesn't ship, not to
teach magpie about OpenClaw.

```bash
magpie plugin list
magpie plugin add @magpie-community/opencode-mimo-auth@latest
magpie plugin login <provider>
magpie plugin on|off <name>
magpie plugin options <name> '<json>'
```
