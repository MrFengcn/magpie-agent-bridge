# Platform differences

magpie itself runs on macOS, Windows and Linux, and so does this skill. Everything
below is what changes between them.

## Installing magpie

```bash
# any platform (the script picks the right asset)
curl -fsSL https://usemagpie.ai/install.sh | sh

# behind a firewall
curl -fsSL https://usemagpie.ai/install.sh | sh -- --proxy http://127.0.0.1:1082

# or from source
go install github.com/yetone/magpie@latest
```

Official builds are signed and notarised on macOS and update themselves. Docker
(`usemagpie.ai/docs/docker`) and Termux are also supported if you want the gateway
on a server or on Android.

## Where the binary lives

| Platform | Path | Notes |
|---|---|---|
| macOS | `/Applications/magpie.app/Contents/MacOS/magpie` | the `.app` bundle; also `~/Applications/` |
| macOS (Homebrew) | `/opt/homebrew/bin/magpie` | |
| Windows | `%LOCALAPPDATA%\magpie\magpie.exe` | per-user install |
| Linux | `~/.local/bin/magpie` | or `/usr/local/bin/magpie` |

`magpie_bridge.py` looks on `PATH` first, then these locations.

## Config directories

| | macOS | Windows | Linux |
|---|---|---|---|
| user config | `~/.config`, `~/.local/share` | `%APPDATA%` (roaming), `%LOCALAPPDATA%` (local) | `~/.config`, `~/.local/share` |
| XDG override | `~/.config` | — | `$XDG_CONFIG_HOME` |
| app data | `~/Library/Application Support` | `%LOCALAPPDATA%` | `~/.local/share` |

## Per-agent config paths

| Agent | macOS | Windows | Linux |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | `~/.claude/settings.json` | `~/.claude/settings.json` |
| Codex | `~/.codex/config.toml` | `~/.codex/config.toml` | `~/.codex/config.toml` |
| **Hermes** | `~/.hermes/config.yaml` | `%LOCALAPPDATA%\hermes\config.yaml` | `$HERMES_HOME` or `~/.hermes/config.yaml` |
| Gemini CLI | `~/.gemini/settings.json` + `~/.gemini/.env` | `~/.gemini/settings.json` | `~/.gemini/settings.json` |
| OpenCode | `~/.config/opencode/opencode.json` | `~/.config/opencode/opencode.json` | `$XDG_CONFIG_HOME/opencode/opencode.json` |
| Qwen Code | `~/.qwen/settings.json` | `~/.qwen/settings.json` | `~/.qwen/settings.json` |
| dsh | `~/.dsh/profiles/*/cordis.patch.yml` | `%USERPROFILE%\.dsh\...` | `~/.dsh/...` |
| Goose | `~/.config/goose/config.yaml` | `%APPDATA%\goose\config.yaml` | `~/.config/goose/config.yaml` |
| Zed | `~/.config/zed/settings.json` | `%APPDATA%\Zed\settings.json` | `~/.config/zed/settings.json` |
| Cursor CLI | `~/.cursor/cli-config.json` | `~/.cursor/cli-config.json` | `~/.cursor/cli-config.json` |
| Copilot CLI | `~/.copilot/settings.json` | `~/.copilot/settings.json` | `~/.copilot/settings.json` |
| VS Code Chat | `~/Library/Application Support/Code/User/settings.json` | `%APPDATA%\Code\User\settings.json` | `~/.config/Code/User/settings.json` |
| VS Code Insiders | `~/Library/Application Support/Code - Insiders/User/…` | `%APPDATA%\Code - Insiders\User\…` | `~/.config/Code - Insiders/User/…` |
| VSCodium | `~/Library/Application Support/VSCodium/User/…` | `%APPDATA%\VSCodium\User\…` | `~/.config/VSCodium/User/…` |
| Raycast | `~/.config/raycast/ai/providers.yaml` | `~/.config/raycast/ai/providers.yaml` | not supported |
| Kimi Code | `~/.kimi/config.toml` | `%APPDATA%\kimi\config.toml` | `~/.kimi/config.toml` |
| Droid (Factory) | `~/.factory/settings.json` | `~/.factory/settings.json` | `~/.factory/settings.json` |
| Cline | `~/.cline/data/settings/providers.json` | `~/.cline/data/settings/providers.json` | `~/.cline/data/settings/providers.json` |
| WorkBuddy | `~/.workbuddy/models.json` | `~/.workbuddy/models.json` | `~/.workbuddy/models.json` |

Many agents also honour their own override env var — `$OPENCODE_CONFIG_DIR`,
`$QODER_CONFIG_DIR`, `$DSH_HOME`, `$KIMI_SHARE_DIR`, `$FACTORY_HOME_OVERRIDE`,
`$HERMES_HOME`, `$QWEN_HOME`, `$WORKBUDDY_CONFIG_DIR`, `$XDG_CONFIG_HOME`. Prefer
those over hard-coded paths.

## Running the gateway headlessly

On a server or over SSH, magpie can serve the gateway without the desktop app:

```bash
magpie web --addr 0.0.0.0:3425 --lan --no-open --gateway
```

`--gateway` means gateway mode: no Agents, Sessions or Library pages. For a TLS
endpoint behind a reverse proxy:

```bash
magpie web --tls-cert server.crt --tls-key server.key --no-open
```

### Gateway keys

The local token is literally `magpie`. To share the gateway with another machine,
turn on **Settings → Network and sharing → Share on local network**, then create a
named gateway key:

```bash
magpie gateway-key add "Remote laptop"        # prints the credential once
magpie gateway-key list
magpie gateway-key rotate <id>
magpie gateway-key remove <id>
magpie gateway-key limit <id> week --tokens 2m --cost 5
```

A key can be restricted to certain models (`magpie gateway-key models <id> openai/gpt-5`)
and certain accounts. Requests send no gateway key are not limited.

## WSL

On Windows, magpie wires the agents inside WSL distributions too, and counts their
sessions. The Windows agent list and the WSL one are separate.

## Running the skill's script on any platform

`scripts/magpie_bridge.py` is standard-library Python 3.9+ — no pip install, no
virtualenv:

```bash
python3 scripts/magpie_bridge.py doctor     # macOS, Linux
py scripts\magpie_bridge.py doctor          # Windows
```

It has been run on macOS (arm64). On Windows and Linux it uses the same code paths
with different path resolution; the gateway calls are plain HTTP via `urllib`, so
there is nothing platform-specific to install.

## Path separators in configs

- macOS/Linux configs use `/`
- Windows configs are mostly the same; VS Code's `chatLanguageModels.json` and Raycast's
  `providers.yaml` use `\` in Windows paths

The bridge writes forward slashes and lets each agent normalise.
