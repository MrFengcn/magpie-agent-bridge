#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""magpie -> OpenClaw model sync.

magpie's model catalog lives in the running gateway (http://127.0.0.1:3425/v1/models)
and changes whenever a provider plugin, account or routing group is added. OpenClaw
is not one of the agents magpie knows, so nothing pushes those changes into
~/.openclaw/openclaw.json — this script is the missing push.

It syncs the two kinds of id that are safe to address as `magpie/<id>` in OpenClaw:

    group/<name>   routing group  (fails over between accounts — preferred)
    auto/<model>   auto group     (one logical model, several providers behind it)

Bare `provider/model` ids are deliberately skipped: their model part can itself
contain slashes (openrouter/openai/gpt-6.1-terra), which OpenClaw mis-splits when
addressing the model as `provider/<model>`.

A model must appear in FOUR places in openclaw.json, all of them:

    1. models.providers.magpie.models[]
    2. agents.defaults.models["magpie/<id>"]        (registry)
    3. agents.defaults.modelPolicy.allow[]          (the sneaky one — miss it and
       the model is invisible in the picker and the default silently reverts)
    4. agents.defaults.model.primary                (only when it should be default)

The script never touches `primary`. If a sync removes the model `primary` points
at, it says so and leaves the decision to you.

Usage:
    magpie_openclaw_sync.py             sync if needed, restart gateway if it changed
    magpie_openclaw_sync.py --dry-run   show what would change, touch nothing
    magpie_openclaw_sync.py --no-restart   write the config but leave the gateway alone
    magpie_openclaw_sync.py --force     rewrite + restart even when nothing changed

Exit codes: 0 ok / up to date, 1 error, 2 nothing to do (only with --dry-run).
Standard library only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

GATEWAY = "http://127.0.0.1:3425"
GATEWAY_KEY = "magpie"
OPENCLAW_HEALTH = "http://127.0.0.1:18789/health"
MAX_OUTPUT_TOKENS = 131072  # OpenClaw's ceiling; magpie advertises up to 524288

HOME = Path.home()
CONFIG = Path(os.environ.get("OPENCLAW_CONFIG_PATH") or (HOME / ".openclaw" / "openclaw.json"))
LOG_DIR = HOME / ".hermes" / "logs"
LOG_FILE = LOG_DIR / "magpie-openclaw-sync.log"
MIN_EXPECTED = 5  # fewer group/auto than this => gateway is mid-restart, do nothing

_lockfile = HOME / ".cache" / "magpie-openclaw-sync.lock"


# --------------------------------------------------------------------- log ----
def log(msg: str, notify: bool = True) -> None:
    """notify=True prints to stdout as well as the file.

    stdout is what a `no_agent` cron job delivers to the chat, so the routine
    "nothing to do" line stays file-only — otherwise Walter gets a message every
    tick for the rest of time. Only changes and actionable failures notify.
    """
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    if notify:
        print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class AcquireLock:
    """One sync at a time — launchd can fire WatchPaths while a run is in flight."""

    def __enter__(self):
        _lockfile.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(_lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - _lockfile.stat().st_mtime
            if age <= 900:
                raise SystemExit(f"another sync is running (lock {int(age)}s old)")
            _lockfile.unlink(missing_ok=True)  # stale lock
            fd = os.open(str(_lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        _lockfile.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------- gateway ----
def openclaw_bin() -> str | None:
    return shutil.which("openclaw") or (
        "/opt/homebrew/bin/openclaw" if Path("/opt/homebrew/bin/openclaw").exists() else None
    )


def gateway_models() -> list[dict]:
    req = urllib.request.Request(
        f"{GATEWAY}/v1/models", headers={"Authorization": f"Bearer {GATEWAY_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp).get("data", [])


def pick_models(models: list[dict]) -> list[dict]:
    return [m for m in models if m.get("id", "").startswith(("group/", "auto/"))]


def model_entry(m: dict) -> dict:
    ctx = m.get("context_window") or m.get("context_length") or 200000
    out = m.get("max_output_tokens") or 64000
    return {
        "id": m["id"],
        "name": m.get("display_name") or m["id"],
        "reasoning": bool(m.get("reasoning")),
        "input": m.get("modalities", {}).get("input") or ["text"],
        "contextWindow": ctx,
        "maxTokens": min(out, MAX_OUTPUT_TOKENS),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }


# ---------------------------------------------------------------- config -----
def read_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{CONFIG} not found — is OpenClaw installed?")
    except Exception as e:
        raise SystemExit(f"cannot read {CONFIG}: {e}")


def write_config(cfg: dict) -> None:
    tmp = CONFIG.with_suffix(CONFIG.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(CONFIG)


def validate_config() -> tuple[bool, str]:
    """Validate the file this script is about to write.

    `openclaw config validate` picks its own config path and ignores
    OPENCLAW_CONFIG_PATH, so with a different HOME it would validate a different
    file than the one being synced. Pass the target explicitly and treat a
    mismatch as "could not validate" rather than "invalid".
    """
    exe = openclaw_bin()
    if not exe:
        return True, "(openclaw binary not found — skipped validation)"
    # `openclaw config validate` reads the file named by OPENCLAW_CONFIG_PATH,
    # but only when that variable is in its environment. Pass it explicitly so
    # the file being validated is always the file being written.
    env = dict(os.environ, OPENCLAW_CONFIG_PATH=str(CONFIG))
    try:
        p = subprocess.run(
            [exe, "config", "validate"],
            capture_output=True, text=True, timeout=120, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"validate could not run: {e}"
    out = (p.stdout + p.stderr).strip()
    # the CLI reports the file it checked; if it is not ours, the check is
    # meaningless — do not mistake that for a broken config
    if p.returncode != 0 and str(CONFIG) not in out and "Config valid" not in out:
        return True, f"(validate did not report on {CONFIG} — skipped)"
    return p.returncode == 0, out


def read_primary(defaults: dict) -> str | None:
    """`agents.defaults.model` is written both ways in the wild: OpenClaw's
    gateway rewrites it as a bare string on some paths, while hand edits and
    older configs keep `{"primary": "<ref>"}`. Handle both — a sync must not
    crash on a shape it didn't create."""
    m = defaults.get("model")
    if isinstance(m, dict):
        return m.get("primary") or None
    if isinstance(m, str):
        return m or None
    return None


def compute_plan(cfg: dict, picked: list[dict], all_ids: set[str]) -> dict:
    """What has to change for OpenClaw to match the gateway."""
    providers = cfg.get("models", {}).get("providers", {})
    mag = providers.get("magpie") or {}
    cur_models = mag.get("models", []) or []
    cur_ids = {m.get("id") for m in cur_models}
    want_ids = {m["id"] for m in picked}

    defaults = cfg.get("agents", {}).get("defaults", {})
    registry = defaults.get("models", {}) or {}
    allow = defaults.get("modelPolicy", {}).get("allow", []) or []

    add = sorted(want_ids - cur_ids)

    # a ref may be dropped only when the gateway no longer serves that id at all —
    # not when the id merely stopped being a group/auto
    def stale(refs) -> list[str]:
        return sorted(
            r for r in refs
            if isinstance(r, str) and r.startswith("magpie/") and r[len("magpie/"):] not in all_ids
        )

    drop_registry = stale(registry.keys())
    drop_allow = stale(allow)

    # The provider's model list is not the whole story. A model can be listed in
    # models.providers.magpie.models[] yet missing from the registry or from
    # modelPolicy.allow — the exact failure this whole skill exists to prevent
    # ("invisible in the picker, default silently reverts"). Compare all three
    # lists against what the gateway serves, not just the provider's.
    missing_registry = sorted(
        ref for ref in (f"magpie/{mid}" for mid in want_ids) if ref not in registry
    )
    missing_allow = sorted(
        ref for ref in (f"magpie/{mid}" for mid in want_ids) if ref not in allow
    )

    wire_ok = (
        bool(mag)
        and mag.get("baseUrl") == f"{GATEWAY}/v1"
        and mag.get("apiKey") == GATEWAY_KEY
        and mag.get("api") == "openai-completions"
    )

    # A model whose id is unchanged may still have different metadata (a new
    # context window, a different display name, a higher output cap). Comparing
    # ids alone would leave the stale entry in place forever, so compare the
    # full entries — a difference means the file must be rewritten.
    want_entries = {e["id"]: e for e in (model_entry(m) for m in picked)}
    cur_entries = {m.get("id"): m for m in cur_models}
    drift = sorted(
        mid for mid in want_ids
        if mid in cur_entries and cur_entries[mid] != want_entries[mid]
    )

    unchanged = (
        not add and not drop_registry and not drop_allow and not drift
        and not missing_registry and not missing_allow
        and wire_ok and len(cur_ids) == len(want_ids)
    )
    return {
        "add": add,
        "drop_registry": drop_registry,
        "drop_allow": drop_allow,
        "drift": drift,
        "missing_registry": missing_registry,
        "missing_allow": missing_allow,
        "wire_ok": wire_ok,
        "cur": sorted(cur_ids),
        "want": sorted(want_ids),
        "unchanged": unchanged,
        "entries": [model_entry(m) for m in picked],
    }


def apply_plan(cfg: dict, plan: dict) -> int:
    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    providers["magpie"] = {
        "baseUrl": f"{GATEWAY}/v1",
        "apiKey": GATEWAY_KEY,
        "api": "openai-completions",
        "timeoutSeconds": 180,
        "headers": {"User-Agent": "openclaw"},
        "models": plan["entries"],
    }

    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    registry = defaults.setdefault("models", {})
    allow = defaults.setdefault("modelPolicy", {}).setdefault("allow", [])

    for ref in plan["drop_registry"]:
        registry.pop(ref, None)
    for ref in plan["drop_allow"]:
        if ref in allow:
            allow.remove(ref)

    for mid in plan["add"]:
        ref = f"magpie/{mid}"
        registry.setdefault(ref, {})
        if ref not in allow:
            allow.append(ref)

    # repair a model that is in the provider's list but missing from the
    # registry or from modelPolicy.allow — the failure mode that makes a model
    # invisible in the picker while everything "looks" configured
    for ref in plan.get("missing_registry", []):
        registry.setdefault(ref, {})
    for ref in plan.get("missing_allow", []):
        if ref not in allow:
            allow.append(ref)
    # drifted ids are refreshed by the wholesale provider rewrite above
    repaired = len(set(plan.get("missing_registry", [])) | set(plan.get("missing_allow", [])))
    return len(plan["add"]) + len(plan.get("drift", [])) + repaired


# --------------------------------------------------------------- gateway ops -
def gateway_running() -> bool:
    try:
        with urllib.request.urlopen(OPENCLAW_HEALTH, timeout=5) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def restart_gateway(timeout: int = 150) -> bool:
    exe = openclaw_bin()
    if not exe:
        log("✗ openclaw binary not found — restart it by hand")
        return False
    # the gateway refuses to restart while running; stop it first
    subprocess.run([exe, "gateway", "stop", "--force"], capture_output=True, text=True, timeout=180)
    subprocess.run([exe, "gateway", "start"], capture_output=True, text=True, timeout=180)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if gateway_running():
            return True
        time.sleep(5)
    return False


# -------------------------------------------------------------------- main ---
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    ap.add_argument("--no-restart", action="store_true", help="write config, leave the gateway alone")
    ap.add_argument("--force", action="store_true", help="rewrite and restart even if nothing changed")
    args = ap.parse_args()

    try:
        models = gateway_models()
    except Exception as e:  # noqa: BLE001
        log(f"✗ magpie gateway unreachable ({e}) — is the magpie app running? nothing done",
            notify=False)
        return 0

    picked = pick_models(models)
    if len(picked) < MIN_EXPECTED:
        # the gateway is up but its catalog looks half-loaded; refuse to gut the config
        log(f"✗ gateway served only {len(picked)} group/auto models (<{MIN_EXPECTED}) — "
            f"looks mid-restart, nothing done", notify=False)
        return 0

    cfg = read_config()
    all_ids = {m.get("id") for m in models}
    plan = compute_plan(cfg, picked, all_ids)

    if plan["unchanged"] and not args.force:
        log(f"up to date — {len(plan['want'])} magpie models already in {CONFIG.name}", notify=False)
        return 0

    primary = read_primary(cfg.get("agents", {}).get("defaults", {}))
    gone_primary = None
    if primary and primary.startswith("magpie/") and primary[len("magpie/"):] not in all_ids:
        gone_primary = primary

    if plan["add"]:
        log("+ add      : " + ", ".join(plan["add"]))
    if plan["drop_allow"] or plan["drop_registry"]:
        log("- remove   : " + ", ".join(sorted(set(plan["drop_allow"]) | set(plan["drop_registry"]))))
    if plan.get("drift"):
        log("~ update   : " + ", ".join(plan["drift"]) + " (metadata changed)")
    if plan.get("missing_registry") or plan.get("missing_allow"):
        fixed = sorted(set(plan.get("missing_registry", [])) | set(plan.get("missing_allow", [])))
        log("~ repair   : " + ", ".join(fixed) + " (missing from registry/allow)")
    if not plan["wire_ok"]:
        log("~ rewire   : provider magpie block was missing or pointed elsewhere")
    if gone_primary:
        log(f"⚠ primary {gone_primary} is no longer served by magpie — left as-is, "
            f"OpenClaw will fall back. Set a new one if that matters.")

    if args.dry_run:
        n_repair = len(set(plan.get("missing_registry", [])) | set(plan.get("missing_allow", [])))
        log(f"dry run — nothing written ({len(plan['add'])} to add, "
            f"{len(set(plan['drop_allow']) | set(plan['drop_registry']))} to drop, "
            f"{len(plan.get('drift', []))} to update, {n_repair} to repair)",
            notify=False)
        return 2

    backup = CONFIG.with_suffix(CONFIG.suffix + ".bak-magpie-sync")
    shutil.copy(CONFIG, backup)
    log(f"backup: {backup}")

    # A config that already failed validation must not be blamed on this sync:
    # only roll back when we turned a passing config into a failing one.
    ok_before, _ = validate_config()

    n = apply_plan(cfg, plan)
    write_config(cfg)
    ok, out = validate_config()
    if not ok:
        if ok_before:
            shutil.copy(backup, CONFIG)
            log("✗ openclaw config validate FAILED — rolled back to the backup")
            for line in (out or "").splitlines()[:15]:
                log(f"    {line}")
            return 1
        log("⚠ validate is failing, but it was failing before this sync too — "
            "not rolling back. The pre-existing problem:", notify=True)
        for line in (out or "").splitlines()[:8]:
            log(f"    {line}", notify=False)
    else:
        log(f"✓ wrote {n} new magpie models into {CONFIG.name} (validate OK)")

    if args.no_restart:
        log("left the gateway alone (--no-restart); run `openclaw gateway stop --force && "
            "openclaw gateway start` to pick it up")
        return 0

    if not gateway_running():
        log("gateway was not running — nothing to restart "
            "(it will read the new config on next start)", notify=False)
        return 0

    log("restarting the OpenClaw gateway ...")
    if restart_gateway():
        log("✓ gateway back up — new models live")
        return 0
    log("✗ gateway did not come back within 150s — check `openclaw gateway status`")
    return 1


if __name__ == "__main__":
    try:
        with AcquireLock():
            sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"✗ {type(e).__name__}: {e}")
        sys.exit(1)
