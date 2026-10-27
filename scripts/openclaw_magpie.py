#!/usr/bin/env python3
"""openclaw-magpie — point OpenClaw at magpie's local gateway.

magpie natively drives Hermes, Codex, Claude Code, Qwen Code, OpenCode and ~60
other agents — but not OpenClaw: its agent list is compiled into the binary and
its plugin mechanism extends providers, not agents.

So OpenClaw has to be wired by hand. This script does that part: it writes the
provider into openclaw.json, syncs the four places a model must appear, validates
the config and verifies the result with a real request.

macOS, Windows and Linux. Python 3.9+, standard library only.

Usage:
    openclaw-magpie doctor     # is the gateway up? is OpenClaw already wired?
    openclaw-magpie list       # models the gateway serves
    openclaw-magpie install    # wire OpenClaw to the gateway
    openclaw-magpie uninstall  # restore the previous config
    openclaw-magpie verify     # make a real request through OpenClaw
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0.0"

GATEWAY = "http://127.0.0.1:3425"
GATEWAY_KEY = "magpie"

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"

HOME = Path.home()


# --------------------------------------------------------------- helpers ----

def openclaw_config() -> Path:
    """Where OpenClaw keeps its config on this platform."""
    env = os.environ.get("OPENCLAW_CONFIG_PATH")
    if env:
        return Path(env)
    return HOME / ".openclaw" / "openclaw.json"


def openclaw_bin() -> str | None:
    return shutil.which("openclaw")


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as e:
        return 126, str(e)


def find_magpie() -> str | None:
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


# --------------------------------------------------------------- gateway ----

def gateway_models() -> list[dict]:
    req = urllib.request.Request(
        f"{GATEWAY}/v1/models", headers={"Authorization": f"Bearer {GATEWAY_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp).get("data", [])


def gateway_healthy() -> tuple[bool, str]:
    try:
        models = gateway_models()
        return True, f"{len(models)} models"
    except urllib.error.URLError as e:
        return False, f"cannot reach {GATEWAY} ({e.reason}) — is magpie running?"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def gateway_call(model: str, prompt: str = "Reply with exactly: OK", timeout: int = 60) -> tuple[bool, str]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
    }).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {GATEWAY_KEY}"},
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


def pick_models(all_models: list[dict]) -> list[dict]:
    """Routing groups and auto groups only.

    Bare `provider/model` ids are skipped: their model part may itself contain
    slashes (e.g. `openrouter/openai/gpt-6.1-terra`), which OpenClaw would
    mis-split when addressing a model as `provider/model`.
    """
    return [
        m for m in all_models
        if m.get("id", "").startswith("group/") or m.get("id", "").startswith("auto/")
    ]


# ----------------------------------------------------------- openclaw.json ---

def read_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"cannot read {path}: {e}")


def write_config(path: Path, cfg: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def model_entry(m: dict) -> dict:
    """Build an OpenClaw model entry from a gateway model."""
    ctx = m.get("context_window") or m.get("context_length") or 200000
    out = m.get("max_output_tokens") or 64000
    return {
        "id": m["id"],
        "name": m.get("display_name") or m["id"],
        "reasoning": bool(m.get("reasoning")),
        "input": m.get("modalities", {}).get("input") or ["text"],
        "contextWindow": ctx,
        # OpenClaw's own ceiling is lower than what magpie advertises
        "maxTokens": min(out, 131072),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }


def sync_four_places(cfg: dict, entries: list[dict]) -> list[str]:
    """Write the provider and sync the four places a model must appear.

    Missing `modelPolicy.allow` is the sneaky one: the model stays invisible in
    the picker and the default silently reverts.
    """
    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    providers["magpie"] = {
        "baseUrl": f"{GATEWAY}/v1",
        "apiKey": GATEWAY_KEY,
        "api": "openai-completions",
        "timeoutSeconds": 180,
        "headers": {"User-Agent": "openclaw"},
        "models": entries,
    }

    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    registry = defaults.setdefault("models", {})
    policy = defaults.setdefault("modelPolicy", {})
    allow = policy.setdefault("allow", [])

    added = []
    for e in entries:
        ref = f"magpie/{e['id']}"
        if ref not in registry:
            registry[ref] = {}
            added.append(f"defaults.models {ref}")
        if ref not in allow:
            allow.append(ref)
            added.append(f"modelPolicy.allow {ref}")
    return added


def wired_state(cfg: dict) -> dict:
    providers = cfg.get("models", {}).get("providers", {})
    mag = providers.get("magpie")
    defaults = cfg.get("agents", {}).get("defaults", {})
    registry = defaults.get("models", {})
    allow = defaults.get("modelPolicy", {}).get("allow", [])
    models = mag.get("models", []) if mag else []
    return {
        "provider": bool(mag),
        "baseUrl": mag.get("baseUrl") if mag else None,
        "api": mag.get("api") if mag else None,
        "models": len(models),
        "in_registry": sum(1 for m in models if f"magpie/{m.get('id')}" in registry),
        "in_allow": sum(1 for m in models if f"magpie/{m.get('id')}" in allow),
        "primary": defaults.get("model", {}).get("primary"),
    }


# ------------------------------------------------------------------ cmds -----

def cmd_doctor(_args) -> int:
    print(f"openclaw-magpie {VERSION}")
    print(f"platform        : {'macOS' if IS_MAC else 'Windows' if IS_WINDOWS else 'Linux'}")
    print(f"openclaw binary : {openclaw_bin() or 'NOT FOUND'}")
    print(f"magpie binary   : {find_magpie() or 'NOT FOUND'}")
    print(f"config          : {openclaw_config()}")

    ok, detail = gateway_healthy()
    print(f"gateway {GATEWAY} : {'OK' if ok else 'UNREACHABLE'} — {detail}")
    if not ok:
        print("\nStart magpie first — it serves the gateway while running.")
        return 1

    path = openclaw_config()
    if not path.exists():
        print("\nNo openclaw.json yet — run `openclaw-magpie install`.")
        return 1

    cfg = read_config(path)
    st = wired_state(cfg)
    print("\nOpenClaw wiring:")
    print(f"  provider magpie     : {'✓' if st['provider'] else '✗'}")
    if st["provider"]:
        print(f"    baseUrl           : {st['baseUrl']}")
        print(f"    api               : {st['api']}")
        print(f"    models            : {st['models']}")
        print(f"    in defaults.models: {st['in_registry']}/{st['models']}")
        print(f"    in modelPolicy    : {st['in_allow']}/{st['models']}")
    print(f"  default model       : {st['primary']}")
    return 0


def cmd_list(_args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"gateway unreachable: {detail}", file=sys.stderr)
        return 1
    models = gateway_models()
    picked = pick_models(models)
    print(f"{len(models)} models served by the gateway; {len(picked)} usable as "
          f"`magpie/<id>` in OpenClaw\n")
    for m in picked:
        kind = "routing group" if m["id"].startswith("group/") else "auto group"
        print(f"  {m['id']:34s} {m.get('display_name',''):24s} ({kind})")
    return 0


def cmd_install(args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"gateway unreachable: {detail}\nStart magpie first.", file=sys.stderr)
        return 1

    models = pick_models(gateway_models())
    if not models:
        print("no routing groups or auto groups found on the gateway", file=sys.stderr)
        return 1
    if args.model:
        models = [m for m in models if args.model in m["id"]]
        if not models:
            print(f"no model matched {args.model!r}", file=sys.stderr)
            return 1

    path = openclaw_config()
    if not path.exists():
        print(f"{path} not found — is OpenClaw installed?", file=sys.stderr)
        return 1

    cfg = read_config(path)
    backup = path.with_suffix(path.suffix + ".bak-openclaw-magpie")
    shutil.copy(path, backup)
    print(f"backup: {backup}")

    entries = [model_entry(m) for m in models]
    added = sync_four_places(cfg, entries)
    write_config(path, cfg)
    print(f"provider 'magpie' written with {len(entries)} models")
    for a in added:
        print(f"  + {a}")

    exe = openclaw_bin()
    if exe:
        rc, out = run([exe, "config", "validate"], timeout=120)
        print(f"\nconfig validate: {'OK' if rc == 0 else 'FAILED'}")
        if rc != 0:
            print(out)
            print(f"\nRestore with: cp '{backup}' '{path}'")
            return 1
        if out:
            for line in out.splitlines():
                print(f"  {line}")
        print("\nRestart the gateway to pick it up:")
        print("  openclaw gateway stop --force && openclaw gateway start")
        print("  (startup takes 30–60s; check http://127.0.0.1:18789/health)")
    return 0


def cmd_uninstall(_args) -> int:
    path = openclaw_config()
    backup = path.with_suffix(path.suffix + ".bak-openclaw-magpie")
    if not backup.exists():
        print(f"✗ no backup found at {backup}", file=sys.stderr)
        return 1
    shutil.copy(backup, path)
    print(f"✓ restored {path} from {backup}")
    print("Restart the gateway: openclaw gateway stop --force && openclaw gateway start")
    return 0


def cmd_verify(args) -> int:
    ok, detail = gateway_healthy()
    if not ok:
        print(f"✗ gateway unreachable: {detail}", file=sys.stderr)
        return 1

    path = openclaw_config()
    if not path.exists():
        print(f"✗ {path} not found", file=sys.stderr)
        return 1
    cfg = read_config(path)
    st = wired_state(cfg)
    if not st["provider"]:
        print("✗ OpenClaw is not wired to magpie — run `openclaw-magpie install`", file=sys.stderr)
        return 1
    print(f"  provider magpie: {st['baseUrl']} ({st['api']})")
    print(f"  models         : {st['models']} "
          f"(registry {st['in_registry']}/{st['models']}, allow {st['in_allow']}/{st['models']})")

    exe = openclaw_bin()
    if not exe:
        print("✗ openclaw binary not found", file=sys.stderr)
        return 1

    model = args.model or "magpie/group/cheap-first"
    print(f"\nrunning one turn through OpenClaw with {model} ...")
    rc, out = run([exe, "agent", "--session-key", "agent:main:magpie-verify",
                   "--message", args.prompt, "--model", model, "--json"], timeout=300)
    if rc != 0:
        print(f"✗ openclaw agent failed (exit {rc})")
        print(out[:2000])
        return 1

    winner_provider = winner_model = None
    try:
        start = out.index("{")
        payload = json.loads(out[start:])

        def dig(o, path):
            for k in path.split("."):
                if isinstance(o, dict) and k in o:
                    o = o[k]
                else:
                    return None
            return o

        # `openclaw agent --json` puts the trace under result.meta.executionTrace;
        # older builds had it directly under result. Try both.
        trace = (
            dig(payload, "result.meta.executionTrace")
            or dig(payload, "result.executionTrace")
            or dig(payload, "executionTrace")
            or {}
        )
        winner_provider = trace.get("winnerProvider")
        winner_model = trace.get("winnerModel")
        if not winner_provider:
            # fall back to the agent metadata
            meta = dig(payload, "result.meta.agentMeta") or {}
            winner_provider = meta.get("provider")
            winner_model = meta.get("model")
    except Exception as e:  # noqa: BLE001
        print(f"  (could not parse the trace: {e})")

    if winner_provider == "magpie":
        print(f"\n✓ OpenClaw ran on magpie — winner: {winner_provider}/{winner_model}")
        return 0
    print(f"\n✗ OpenClaw did not use magpie (winner: {winner_provider}/{winner_model})")
    print(out[:2000])
    return 1


def main() -> int:
    p = argparse.ArgumentParser(prog="openclaw-magpie",
                                description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="check the gateway and OpenClaw's wiring").set_defaults(fn=cmd_doctor)
    sub.add_parser("list", help="list models the gateway serves").set_defaults(fn=cmd_list)

    pi = sub.add_parser("install", help="wire OpenClaw to the gateway")
    pi.add_argument("--model", help="only models whose id contains this string")
    pi.set_defaults(fn=cmd_install)

    pu = sub.add_parser("uninstall", help="restore the previous config").set_defaults(fn=cmd_uninstall)

    pv = sub.add_parser("verify", help="make a real request through OpenClaw")
    pv.add_argument("--model", default="magpie/group/cheap-first")
    pv.add_argument("--prompt", default="Reply with exactly: OK")
    pv.set_defaults(fn=cmd_verify)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
