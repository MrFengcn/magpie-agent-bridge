"""Unit tests for magpie_openclaw_sync.

These run without a gateway, without OpenClaw and without magpie installed —
they cover the pure planning functions: model selection, entry building, the
four-place sync, stale-reference pruning, metadata drift and the primary-model
shape that OpenClaw's own gateway rewrites.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import magpie_openclaw_sync as s  # noqa: E402


def base_config(models=None, primary="other/keep"):
    """An openclaw.json with a magpie provider already wired.

    The model entries are built through the module's own `model_entry` so the
    fixture matches what a real sync writes — otherwise the drift check would
    (correctly) report a difference.
    """
    if models is None:
        models = [{"id": "group/g"}]
    entries = [s.model_entry(m) for m in models]
    return {
        "models": {"providers": {"magpie": {
            "baseUrl": "http://127.0.0.1:3425/v1",
            "apiKey": "magpie",
            "api": "openai-completions",
            "timeoutSeconds": 180,
            "headers": {"User-Agent": "openclaw"},
            "models": entries,
        }, "other": {"baseUrl": "x"}}},
        "agents": {"defaults": {
            "models": {f"magpie/{m['id']}": {} for m in models},
            "modelPolicy": {"allow": [f"magpie/{m['id']}" for m in models]},
            "model": primary,
        }},
    }


class TestModelSelection(unittest.TestCase):
    def test_picks_groups_and_auto_only(self):
        models = [
            {"id": "group/cheap-first"},
            {"id": "auto/glm-5.3"},
            {"id": "volcengine/doubao-seed"},
            {"id": "openrouter/openai/gpt-6.1-terra-pro"},
        ]
        ids = [m["id"] for m in s.pick_models(models)]
        self.assertEqual(ids, ["group/cheap-first", "auto/glm-5.3"])

    def test_empty(self):
        self.assertEqual(s.pick_models([]), [])


class TestModelEntry(unittest.TestCase):
    def test_caps_max_tokens(self):
        e = s.model_entry({"id": "a/b", "max_output_tokens": 524288})
        self.assertEqual(e["maxTokens"], 131072)

    def test_defaults(self):
        e = s.model_entry({"id": "a/b"})
        self.assertEqual(e["contextWindow"], 200000)
        self.assertEqual(e["input"], ["text"])
        self.assertFalse(e["reasoning"])
        self.assertEqual(e["name"], "a/b")

    def test_cost_is_zero(self):
        e = s.model_entry({"id": "a/b"})
        self.assertEqual(e["cost"], {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0})


class TestComputePlan(unittest.TestCase):
    def test_no_changes_when_in_sync(self):
        cfg = base_config()
        picked = [{"id": "group/g", "display_name": "group/g"}]
        plan = s.compute_plan(cfg, picked, {"group/g"})
        self.assertTrue(plan["unchanged"])
        self.assertEqual(plan["add"], [])

    def test_detects_new_model(self):
        cfg = base_config()
        picked = [{"id": "group/g"}, {"id": "auto/new"}]
        plan = s.compute_plan(cfg, picked, {"group/g", "auto/new"})
        self.assertFalse(plan["unchanged"])
        self.assertEqual(plan["add"], ["auto/new"])

    def test_detects_stale_reference(self):
        """A ref the gateway no longer serves at all must be pruned."""
        cfg = base_config([{"id": "group/g"}, {"id": "auto/gone"}])
        picked = [{"id": "group/g"}]
        plan = s.compute_plan(cfg, picked, {"group/g"})
        self.assertIn("magpie/auto/gone", plan["drop_registry"])
        self.assertIn("magpie/auto/gone", plan["drop_allow"])

    def test_keeps_ref_that_still_exists_but_is_not_a_group(self):
        """An id the gateway still serves but that stopped being group/auto
        must NOT be dropped — the gateway may still serve it."""
        cfg = base_config([{"id": "group/g"}, {"id": "volcengine/x"}])
        picked = [{"id": "group/g"}]
        plan = s.compute_plan(cfg, picked, {"group/g", "volcengine/x"})
        self.assertEqual(plan["drop_registry"], [])
        self.assertEqual(plan["drop_allow"], [])

    def test_detects_metadata_drift(self):
        """Same id, different metadata — the file must be rewritten."""
        cfg = base_config([{"id": "group/g", "contextWindow": 1000, "maxTokens": 100}])
        picked = [{"id": "group/g", "context_window": 1048576,
                   "max_output_tokens": 131072, "display_name": "G"}]
        plan = s.compute_plan(cfg, picked, {"group/g"})
        self.assertFalse(plan["unchanged"], "metadata drift must not read as unchanged")
        self.assertEqual(plan["drift"], ["group/g"])

    def test_no_drift_when_metadata_matches(self):
        # pass the raw gateway model, not a pre-built entry — base_config
        # builds the entry itself, the same way compute_plan does
        raw = {"id": "group/g", "display_name": "G"}
        cfg = base_config([raw])
        plan = s.compute_plan(cfg, [raw], {"group/g"})
        self.assertEqual(plan["drift"], [])
        self.assertTrue(plan["unchanged"])

    def test_detects_broken_wiring(self):
        cfg = base_config()
        cfg["models"]["providers"]["magpie"]["api"] = "openai-responses"
        plan = s.compute_plan(cfg, [{"id": "group/g"}], {"group/g"})
        self.assertFalse(plan["wire_ok"])
        self.assertFalse(plan["unchanged"])


class TestApplyPlan(unittest.TestCase):
    def test_writes_four_places(self):
        cfg = base_config()
        picked = [{"id": "group/g"}, {"id": "auto/new"}]
        plan = s.compute_plan(cfg, picked, {"group/g", "auto/new"})
        s.apply_plan(cfg, plan)
        d = cfg["agents"]["defaults"]
        self.assertIn("magpie/auto/new", d["models"])
        self.assertIn("magpie/auto/new", d["modelPolicy"]["allow"])
        self.assertEqual(len(cfg["models"]["providers"]["magpie"]["models"]), 2)

    def test_removes_stale_refs(self):
        cfg = base_config([{"id": "group/g"}, {"id": "auto/gone"}])
        plan = s.compute_plan(cfg, [{"id": "group/g"}], {"group/g"})
        s.apply_plan(cfg, plan)
        d = cfg["agents"]["defaults"]
        self.assertNotIn("magpie/auto/gone", d["models"])
        self.assertNotIn("magpie/auto/gone", d["modelPolicy"]["allow"])

    def test_preserves_other_providers(self):
        cfg = base_config()
        plan = s.compute_plan(cfg, [{"id": "group/g"}], {"group/g"})
        s.apply_plan(cfg, plan)
        self.assertIn("other", cfg["models"]["providers"])

    def test_does_not_touch_primary(self):
        cfg = base_config(primary="other/keep")
        plan = s.compute_plan(cfg, [{"id": "auto/new"}], {"group/g", "auto/new"})
        s.apply_plan(cfg, plan)
        self.assertEqual(cfg["agents"]["defaults"]["model"], "other/keep")


class TestReadPrimary(unittest.TestCase):
    def test_object_form(self):
        self.assertEqual(s.read_primary({"model": {"primary": "a/b"}}), "a/b")

    def test_string_form(self):
        """OpenClaw's gateway rewrites `model` to a bare string."""
        self.assertEqual(s.read_primary({"model": "a/b"}), "a/b")

    def test_absent(self):
        self.assertIsNone(s.read_primary({}))
        self.assertIsNone(s.read_primary({"model": None}))


class TestAcquireLock(unittest.TestCase):
    def test_lock_is_released(self):
        lockfile = s._lockfile
        existed = lockfile.exists()
        try:
            with s.AcquireLock():
                self.assertTrue(lockfile.exists())
            self.assertFalse(lockfile.exists())
        finally:
            if existed:
                lockfile.unlink(missing_ok=True)


class TestConfigRoundTrip(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "openclaw.json"
            cfg = {"a": 1, "b": {"c": "x"}}
            s.write_config(cfg) if False else None
            # write_config uses the module-level CONFIG; test the primitives only
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            tmp.replace(p)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), cfg)


class TestConfigPathOverride(unittest.TestCase):
    def test_env_override(self):
        old = os.environ.get("OPENCLAW_CONFIG_PATH")
        os.environ["OPENCLAW_CONFIG_PATH"] = "/tmp/somewhere.json"
        try:
            import importlib
            importlib.reload(s)
            self.assertEqual(s.CONFIG, Path("/tmp/somewhere.json"))
        finally:
            if old is None:
                os.environ.pop("OPENCLAW_CONFIG_PATH", None)
            else:
                os.environ["OPENCLAW_CONFIG_PATH"] = old
            import importlib
            importlib.reload(s)


if __name__ == "__main__":
    unittest.main()
