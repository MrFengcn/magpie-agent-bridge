#!/usr/bin/env python3
"""magpie-agent-bridge — wire any agent CLI onto magpie's local gateway.

Works on macOS, Windows and Linux. Only the standard library is used.

The gateway at 127.0.0.1:3425 speaks OpenAI Chat Completions, OpenAI Responses and
Anthropic Messages. Any agent that accepts a custom base URL can point at it.

Usage:
    magpie-bridge doctor                 # check gateway + list detected agents
    magpie-bridge list                   # list models the gateway serves
    magpie-bridge install <agent> [...]  # configure agents to use the gateway
    magpie-bridge uninstall <agent>      # restore an agent's previous config
    magpie-bridge show <agent>           # show one agent's current setup
    magpie-bridge verify <agent>         # make a real request through the agent
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = "http://127.0.0.1:3425"
API_KEY = "magpie"
VERSION = "1.0.0"

# ---------------------------------------------------------------- platform ----

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

HOME = Path.home()
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))


def config_dir(kind: str) -> Path:
    """Where an agent keeps its config on this platform."""
    if kind == "xdg":
        return XDG_CONFIG_HOME
    if kind == "appdata":
        return APPDATA
    if kind == "localappdata":
        return LOCALAPPDATA
    if kind == "macos_app_support":
        return HOME / "Library" / "Application Support"
    if kind == "home":
        return HOME
    raise ValueError(kind)


def os_label() -> str:
    if IS_MAC:
        return "macOS"
    if IS_WINDOWS:
        return "Windows"
    if IS_LINUX:
        return "Linux"
    return platform.platform()


# --------------------------------------------------------------- discovery ---

def find_magpie() -> str | None:
    """Locate the magpie binary on PATH or in the usual install spots."""
    found = shutil.which("magpie")
    if found:
        return found
    candidates = []
    if IS_MAC:
        candidates.append("/Applications/magpie.app/Contents/MacOS/magpie")
        candidates.append(str(HOME / "Applications" / "magpie.app" / "Contents" / "MacOS" / "magpie"))
    else:
        candidates += [
            str(HOME / ".local" / "bin" / "magpie"),
            str(Path("/usr/local/bin/magpie")),
            str(Path("/opt/homebrew/bin/magpie")),
        ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def magpie_run(args: list[str], timeout: int = 30) -> tuple[int, str]:
    exe = find_magpie()
    if not exe:
        return 127, "magpie binary not found"
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as e:
        return 126, str(e)


# ------------------------------------------------------------------ gateway ---

def gateway_models() -> list[dict]:
    req = urllib.request.Request(
        f"{GATEWAY}/v1/models", headers={"Authorization": f"Bearer {API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp).get("data", [])


def gateway_healthy() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            f"{GATEWAY}/v1/models", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp).get("data", [])
        return True, f"{len(data)} models"
    except urllib.error.URLError as e:
        return False, f"cannot reach {GATEWAY} ({e.reason})"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def gateway_call(model: str, prompt: str = "Reply with exactly: OK", timeout: int = 60) -> tuple[bool, str]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 32,
        }
    ).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
        text = payload["choices"][0]["message"].get("content") or ""
        return True, text.strip()[:120]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# -------------------------------------------------------------- model sets ---

def pick_models(all_models: list[dict], pattern: str | None) -> list[dict]:
    """Select gateway models for an agent.

    Preference order:
      1. an explicit --model / pattern match on the id
      2. every routing group (`group/*`) and auto group (`auto/*`)

    Bare `provider/model` ids are skipped by default because their model part may
    itself contain slashes (e.g. `openrouter/openai/gpt-6.1-terra`), which is
    ambiguous for agents that address models as `provider/model`.
    """
    if pattern:
        return [m for m in all_models if pattern in m.get("id", "")]
    return [
        m for m in all_models
        if m.get("id", "").startswith("group/") or m.get("id", "").startswith("auto/")
    ]


# --------------------------------------------------------------- json utils --

def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    b = path.with_suffix(path.suffix + f".magpie-bridge-bak")
    shutil.copy(path, b)
    return b


# ------------------------------------------------------------ agent specs ----
# Each spec: config path per platform kind, the file format, and how to inject
# a magpie provider. `kind` selects the platform layout.

def agent_specs() -> dict[str, dict]:
    """Config locations for every agent magpie can drive natively.

    Source: magpie's docs/reference.md "Agents" table. Paths are per platform;
    `macos` / `windows` / `linux` override the default `home`/`xdg` kind.
    """
    return {
        "hermes": {
            "format": "yaml",
            "paths": {
                "home": ".hermes/config.yaml",
                "windows": "AppData/Local/hermes/config.yaml",
            },
            "note": "Hermes Agent. magpie drives this natively: `magpie hermes <model>`.",
        },
        "claude": {
            "format": "json",
            "paths": {
                "home": ".claude/settings.json",
                "windows": ".claude/settings.json",
                "linux": ".claude/settings.json",
            },
            "note": "Claude Code. `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` also work.",
        },
        "codex": {
            "format": "toml",
            "paths": {"home": ".codex/config.toml"},
            "note": "Codex CLI. config.toml — needs a TOML writer.",
        },
        "gemini": {
            "format": "json",
            "paths": {
                "home": ".gemini/settings.json",
                "xdg": "gemini/settings.json",
                "windows": ".gemini/settings.json",
            },
            "note": "Gemini CLI.",
        },
        "opencode": {
            "format": "jsonc",
            "paths": {
                "xdg": "opencode/opencode.json",
                "home": ".config/opencode/opencode.json",
                "windows": ".config/opencode/opencode.json",
            },
            "note": "OpenCode.",
        },
        "qwen": {
            "format": "json",
            "paths": {"home": ".qwen/settings.json", "windows": ".qwen/settings.json"},
            "note": "Qwen Code.",
        },
        "dsh": {
            "format": "yaml",
            "paths": {"home": ".dsh/config.yaml"},
            "note": "DeepSeek Harness.",
        },
        "goose": {
            "format": "yaml",
            "paths": {"xdg": "goose/config.yaml"},
            "note": "Goose.",
        },
        "zed": {
            "format": "json",
            "paths": {
                "xdg": "zed/settings.json",
                "windows": "AppData/Roaming/Zed/settings.json",
            },
            "note": "Zed editor.",
        },
        "crush": {
            "format": "json",
            "paths": {"xdg": "crush/crush.json"},
            "note": "Crush.",
        },
        "cursor": {
            "format": "json",
            "paths": {"home": ".cursor/cli-config.json"},
            "note": "Cursor CLI.",
        },
        "copilot": {
            "format": "json",
            "paths": {"home": ".copilot/settings.json"},
            "note": "Copilot CLI.",
        },
        "mimocode": {
            "format": "jsonc",
            "paths": {"xdg": "mimocode/mimocode.json"},
            "note": "MiMo Code.",
        },
        "workbuddy": {
            "format": "json",
            "paths": {"home": ".workbuddy/models.json"},
            "note": "WorkBuddy.",
        },
        "factory": {
            "format": "json",
            "paths": {"home": ".factory/settings.json"},
            "note": "Droid (Factory).",
        },
        "cline": {
            "format": "json",
            "paths": {"home": ".cline/data/settings/providers.json"},
            "note": "Cline CLI.",
        },
        "kimi": {
            "format": "toml",
            "paths": {"home": ".kimi/config.toml"},
            "note": "Kimi Code.",
        },
        "pi": {
            "format": "json",
            "paths": {"home": ".pi/agent/settings.json"},
            "note": "Pi agent.",
        },
        "muse": {
            "format": "json",
            "paths": {"xdg": "muse/settings.json"},
            "note": "Muse Code.",
        },
        "devin": {
            "format": "json",
            "paths": {"xdg": "devin/config.json"},
            "note": "Devin CLI.",
        },
        "raycast": {
            "format": "yaml",
            "paths": {"xdg": "raycast/ai/providers.yaml"},
            "note": "Raycast AI (macOS/Windows only).",
        },
    }


def resolve_agent_path(spec: dict) -> Path:
    paths = spec["paths"]
    if IS_MAC:
        rel = paths.get("macos") or paths.get("home") or paths.get("xdg")
    elif IS_WINDOWS:
        rel = paths.get("windows") or paths.get("home") or paths.get("xdg")
    else:
        rel = paths.get("linux") or paths.get("xdg") or paths.get("home")
    if rel is None:
        raise ValueError("no path for this platform")
    p = Path(rel)
    return p if p.is_absolute() else HOME / p


# ---------------------------------------------------------- yaml / toml io ----

def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "" or any(c in s for c in ":#{}[],&*?|-<>=!%@`\"'\n") or s.strip() != s:
        return json.dumps(s)
    return s


def yaml_set(path: Path, dotted: str, value) -> None:
    """Set a nested key in a small YAML file, preserving other content.

    Handles the shapes these agent configs use: a path of `a.b.c` where each
    level is a mapping and the leaf is a scalar. Comments, ordering and
    unrelated keys are left alone.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    parts = dotted.split(".")

    def ind(l: str) -> int:
        return len(l) - len(l.lstrip(" "))

    def find_key(lst: list[str], name: str, start: int, level: int) -> int:
        """Index of the `name:` line at exactly `level` indent, or -1."""
        for i in range(start, len(lst)):
            s = lst[i].strip()
            if not s or s.startswith("#"):
                continue
            cur = ind(lst[i])
            if cur < level:
                return -1
            if cur == level and s.split(":", 1)[0].strip() == name:
                return i
        return -1

    def block_end(lst: list[str], i: int) -> int:
        """Index just past the end of the block that starts at line i."""
        base = ind(lst[i])
        j = i + 1
        while j < len(lst):
            if lst[j].strip() and ind(lst[j]) <= base:
                break
            j += 1
        return j

    # locate the parent mapping, if it exists
    parent_idx = -1
    level = 0
    search_from = 0
    for part in parts[:-1]:
        i = find_key(lines, part, search_from, level)
        if i == -1:
            parent_idx = -1
            break
        parent_idx = i
        search_from = i + 1
        level = ind(lines[i]) + 2

    key = parts[-1]
    if parent_idx == -1:
        # the path does not exist yet — create it at the root
        for n, part in enumerate(parts[:-1]):
            lines.append(" " * (n * 2) + f"{part}:")
        lines.append(" " * ((len(parts) - 1) * 2) + f"{key}: {_yaml_scalar(value)}")
    else:
        parent_indent = ind(lines[parent_idx])
        i = find_key(lines, key, parent_idx + 1, parent_indent + 2)
        if i != -1:
            lines[i] = " " * ind(lines[i]) + f"{key}: {_yaml_scalar(value)}"
        else:
            lines.insert(block_end(lines, parent_idx),
                         " " * (parent_indent + 2) + f"{key}: {_yaml_scalar(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def toml_set(path: Path, dotted: str, value) -> None:
    """Set a key in a TOML file using a minimal append/replace strategy.

    Only handles the shapes magpie needs: top-level scalars, `[table]` and
    `[table.sub]` sections. Anything more exotic should use a real TOML parser.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    parts = dotted.split(".")
    table = parts[:-1]
    key = parts[-1]

    header = "[" + ".".join(table) + "]" if table else ""
    value_s = _toml_value(value)

    def find_section(h: str) -> tuple[int, int]:
        start = None
        for i, l in enumerate(lines):
            if l.strip() == h:
                start = i
                break
        if start is None:
            return -1, -1
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith("["):
                return start, j
        return start, len(lines)

    if not table:
        for i, l in enumerate(lines):
            if l.strip().startswith(f"{key} ="):
                lines[i] = f"{key} = {value_s}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return
        lines.append(f"{key} = {value_s}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    start, end = find_section(header)
    if start == -1:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(header)
        lines.append(f"{key} = {value_s}")
    else:
        for i in range(start + 1, end):
            if lines[i].strip().startswith(f"{key} ="):
                lines[i] = f"{key} = {value_s}"
                break
        else:
            lines.insert(end, f"{key} = {value_s}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value))


def json_set(path: Path, dotted: str, value) -> None:
    data = read_json(path)
    parts = dotted.split(".")
    cur = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value
    write_json(path, data)


# ------------------------------------------------------------- installers ----

def gateway_base() -> str:
    return f"{GATEWAY}/v1"


def install_agent(name: str, models: list[dict], pattern: str | None) -> tuple[bool, str]:
    """Point one agent at the magpie gateway.

    Uses magpie's own CLI when it knows the agent (it edits the agent's own
    config format properly, comments and all). Falls back to writing the
    provider block directly for agents magpie doesn't ship.
    """
    exe = find_magpie()
    known = set(magpie_run(["openclaw"])[1].split("(try:")[-1].replace(")", "").replace(" ", "").split(",")) if exe else set()

    if exe and name in known:
        model_id = models[0]["id"] if models else ""
        if not model_id:
            return False, "no models to set"
        rc, out = magpie_run([name, model_id], timeout=60)
        if rc == 0:
            return True, f"magpie set {name} -> {model_id}"
        return False, out

    spec = agent_specs().get(name)
    if not spec:
        return False, f"unknown agent '{name}' and magpie CLI not available to drive it"

    path = resolve_agent_path(spec)
    if not path.exists():
        return False, f"config not found: {path} (is {name} installed?)"

    backup(path)
    fmt = spec["format"]
    try:
        if fmt == "json":
            json_set(path, "env.ANTHROPIC_BASE_URL", gateway_base())
            json_set(path, "env.ANTHROPIC_API_KEY", API_KEY)
            json_set(path, "env.OPENAI_BASE_URL", gateway_base())
            json_set(path, "env.OPENAI_API_KEY", API_KEY)
            json_set(path, "env.GOOGLE_GEMINI_BASE_URL", gateway_base())
            json_set(path, "env.GEMINI_API_KEY", API_KEY)
        elif fmt == "jsonc":
            json_set(path, "provider.magpie.npm", "@ai-sdk/openai-compatible")
            json_set(path, "provider.magpie.options.baseURL", gateway_base())
            json_set(path, "provider.magpie.options.apiKey", API_KEY)
            json_set(path, "provider.magpie.models", {m["id"]: {"name": m.get("display_name", m["id"])} for m in models})
        elif fmt == "yaml":
            yaml_set(path, "env.ANTHROPIC_BASE_URL", gateway_base())
            yaml_set(path, "env.ANTHROPIC_API_KEY", API_KEY)
            yaml_set(path, "env.OPENAI_BASE_URL", gateway_base())
            yaml_set(path, "env.OPENAI_API_KEY", API_KEY)
        elif fmt == "toml":
            toml_set(path, "model_provider", "magpie")
            toml_set(path, "model_providers.magpie.name", "magpie")
            toml_set(path, "model_providers.magpie.base_url", gateway_base())
            toml_set(path, "model_providers.magpie.env_key", "MAGPIE_API_KEY")
        else:
            return False, f"unsupported format {fmt}"
    except Exception as e:  # noqa: BLE001
        return False, f"write failed: {e}"

    return True, f"wrote {path}"


# ------------------------------------------------------------------ cmds -----

def cmd_doctor(_args) -> int:
    print(f"magpie-agent-bridge {VERSION}")
    print(f"platform      : {os_label()} ({platform.machine()})")
    exe = find_magpie()
    print(f"magpie binary : {exe or 'NOT FOUND'}")
    ok, detail = gateway_healthy()
    print(f"gateway {GATEWAY} : {'OK' if ok else 'UNREACHABLE'} — {detail}")
    if not ok:
        print("\nStart magpie first (it serves the gateway while running).")
        return 1
    print("\nDetected agents (magpie's own view):")
    rc, out = magpie_run(["ls"])
    print(out or "  (none)")
    print("\nAgents found on this machine:")
    specs = agent_specs()
    for name, spec in sorted(specs.items()):
        try:
            p = resolve_agent_path(spec)
        except Exception:
            continue
        mark = "✓" if p.exists() else " "
        print(f"  {mark} {name:16s} {p}")
    return 0


def cmd_list(_args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"gateway unreachable: {detail}", file=sys.stderr)
        return 1
    models = gateway_models()
    groups = [m for m in models if m["id"].startswith("group/")]
    autos = [m for m in models if m["id"].startswith("auto/")]
    print(f"{len(models)} models served by the gateway\n")
    print("Routing groups (use these — they fail over between accounts):")
    for m in groups:
        print(f"  {m['id']:34s} {m.get('display_name','')}")
    print("\nAuto groups (one logical model across providers):")
    for m in autos:
        print(f"  {m['id']:34s} {m.get('display_name','')}")
    print("\nAll model ids:")
    for m in models:
        print(f"  {m['id']}")
    return 0


def cmd_install(args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"gateway unreachable: {detail}\nStart magpie first.", file=sys.stderr)
        return 1
    models = pick_models(gateway_models(), args.model)
    if not models:
        print("no models matched", file=sys.stderr)
        return 1
    failures = 0
    for name in args.agents:
        good, msg = install_agent(name, models, args.model)
        print(f"{'✓' if good else '✗'} {name:14s} {msg}")
        if not good:
            failures += 1
    return 1 if failures else 0


def cmd_uninstall(args) -> int:
    specs = agent_specs()
    for name in args.agents:
        spec = specs.get(name)
        if not spec:
            print(f"✗ {name}: unknown agent")
            continue
        path = resolve_agent_path(spec)
        bak = path.with_suffix(path.suffix + ".magpie-bridge-bak")
        if bak.exists():
            shutil.copy(bak, path)
            print(f"✓ {name}: restored {path} from backup")
        else:
            print(f"✗ {name}: no backup found for {path}")
    return 0


def cmd_show(args) -> int:
    specs = agent_specs()
    for name in args.agents:
        spec = specs.get(name)
        if not spec:
            print(f"✗ {name}: unknown agent")
            continue
        path = resolve_agent_path(spec)
        print(f"\n=== {name} ===")
        print(f"  config: {path} ({'exists' if path.exists() else 'missing'})")
        print(f"  note  : {spec.get('note','')}")
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = [l for l in text.splitlines() if "3425" in l or "magpie" in l.lower()]
            if hits:
                print("  magpie references:")
                for l in hits[:10]:
                    print(f"    {l.strip()}")
            else:
                print("  (no magpie reference in the config)")
    return 0


def cmd_verify(args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"✗ gateway unreachable: {detail}", file=sys.stderr)
        return 1
    models = pick_models(gateway_models(), args.model)
    if not models:
        print("✗ no models matched", file=sys.stderr)
        return 1
    failures = 0
    for m in models:
        good, out = gateway_call(m["id"], args.prompt)
        print(f"{'✓' if good else '✗'} {m['id']:34s} {out}")
        if not good:
            failures += 1
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(prog="magpie-bridge", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="check the gateway and list detected agents").set_defaults(fn=cmd_doctor)
    sub.add_parser("list", help="list models the gateway serves").set_defaults(fn=cmd_list)

    pi = sub.add_parser("install", help="point agents at the gateway")
    pi.add_argument("agents", nargs="+")
    pi.add_argument("--model", help="only models whose id contains this string")
    pi.set_defaults(fn=cmd_install)

    pu = sub.add_parser("uninstall", help="restore an agent's previous config")
    pu.add_argument("agents", nargs="+")
    pu.set_defaults(fn=cmd_uninstall)

    ps = sub.add_parser("show", help="show one agent's current setup")
    ps.add_argument("agents", nargs="+")
    ps.set_defaults(fn=cmd_show)

    pv = sub.add_parser("verify", help="make a real request through the gateway")
    pv.add_argument("--model", help="only models whose id contains this string")
    pv.add_argument("--prompt", default="Reply with exactly: OK")
    pv.set_defaults(fn=cmd_verify)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
