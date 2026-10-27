# Platform differences

The skill's script is plain Python 3.9+ with only the standard library, so it runs
unchanged on macOS, Windows and Linux. What differs is where things live.

## Installing magpie

```bash
# any platform (the script picks the right asset)
curl -fsSL https://usemagpie.ai/install.sh | sh

# behind a firewall
curl -fsSL https://usemagpie.ai/install.sh | sh -- --proxy http://127.0.0.1:1082

# or from source
go install github.com/yetone/magpie@latest
```

Official macOS builds are signed and notarised and update themselves. Docker
(`usemagpie.ai/docs/docker`) and Termux are also supported if you want the gateway
on a server or on Android.

## Where the magpie binary lives

| Platform | Path | Notes |
|---|---|---|
| macOS | `/Applications/magpie.app/Contents/MacOS/magpie` | the `.app` bundle; also `~/Applications/` |
| macOS (Homebrew) | `/opt/homebrew/bin/magpie` | |
| Windows | `%LOCALAPPDATA%\magpie\magpie.exe` | per-user install |
| Linux | `~/.local/bin/magpie` | or `/usr/local/bin/magpie` |

The script looks on `PATH` first, then these locations.

## OpenClaw's config and gateway

Same on all three platforms — OpenClaw uses `~/.openclaw` everywhere:

| | macOS | Windows | Linux |
|---|---|---|---|
| config | `~/.openclaw/openclaw.json` | `%USERPROFILE%\.openclaw\openclaw.json` | `$HOME/.openclaw/openclaw.json` |
| gateway | `127.0.0.1:18789` | same | same |
| health check | `curl -s http://127.0.0.1:18789/health` | same | same |

`OPENCLAW_CONFIG_PATH` overrides the config location. The script honours it — that
is how it can be pointed at a copy for testing without touching the live config:

```bash
OPENCLAW_CONFIG_PATH=/tmp/openclaw.json python3 scripts/openclaw_magpie.py install
```

## Running the script

```bash
python3 scripts/openclaw_magpie.py doctor     # macOS, Linux
py scripts\openclaw_magpie.py doctor          # Windows
```

It has been run on macOS (arm64). On Windows and Linux the same code paths apply
with different path resolution; the gateway calls are plain HTTP through `urllib`,
so there is nothing platform-specific to install.

## Running the gateway headlessly

On a server or over SSH, magpie can serve the gateway without the desktop app:

```bash
magpie web --addr 0.0.0.0:3425 --lan --no-open --gateway
```

`--gateway` means gateway mode: no Agents, Sessions or Library pages. For TLS
behind a reverse proxy:

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
and certain accounts. Requests that send no gateway key are not limited.

## WSL

On Windows, magpie wires the agents inside WSL distributions too, and counts their
sessions. The Windows agent list and the WSL one are separate.

## Path separators

- macOS and Linux configs use `/`
- Windows configs are mostly the same; VS Code's `chatLanguageModels.json` uses `\`
  in Windows paths

The bridge writes forward slashes and lets each agent normalise.
