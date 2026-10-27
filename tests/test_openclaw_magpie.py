"""Unit tests for openclaw_magpie.

These run without a gateway, without OpenClaw and without magpie installed —
they cover the pure functions: model selection, model entry building, and the
four-place sync into openclaw.json.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import openclaw_magpie as om  # noqa: E402


class TestModelSelection(unittest.TestCase):
    def test_picks_groups_and_auto_only(self):
        models = [
            {"id": "group/cheap-first"},
            {"id": "auto/glm-5.3"},
            {"id": "volcengine/doubao-seed-evolving"},
            {"id": "openrouter/openai/gpt-6.1-terra-pro"},
        ]
        ids = [m["id"] for m in om.pick_models(models)]
        self.assertIn("group/cheap-first", ids)
        self.assertIn("auto/glm-5.3", ids)
        # bare provider/model ids are excluded: the model part may contain
        # slashes, which OpenClaw would mis-split as provider/model
        self.assertNotIn("openrouter/openai/gpt-6.1-terra-pro", ids)

    def test_empty_gateway_yields_nothing(self):
        self.assertEqual(om.pick_models([]), [])
        self.assertEqual(om.pick_models([{"id": "x/y"}]), [])


class TestModelEntry(unittest.TestCase):
    def test_entry_shape(self):
        entry = om.model_entry({
            "id": "group/cheap-first",
            "display_name": "cheap",
            "reasoning": True,
            "modalities": {"input": ["text", "image"]},
            "context_window": 1048576,
            "max_output_tokens": 524288,
        })
        self.assertEqual(entry["id"], "group/cheap-first")
        self.assertEqual(entry["name"], "cheap")
        self.assertTrue(entry["reasoning"])
        self.assertEqual(entry["input"], ["text", "image"])
        self.assertEqual(entry["contextWindow"], 1048576)
        # capped at OpenClaw's own ceiling
        self.assertEqual(entry["maxTokens"], 131072)

    def test_max_tokens_capped(self):
        entry = om.model_entry({"id": "a/b", "max_output_tokens": 999999})
        self.assertEqual(entry["maxTokens"], 131072)

    def test_defaults_when_metadata_missing(self):
        entry = om.model_entry({"id": "a/b"})
        self.assertEqual(entry["contextWindow"], 200000)
        self.assertEqual(entry["input"], ["text"])
        self.assertFalse(entry["reasoning"])
        self.assertEqual(entry["name"], "a/b")

    def test_cost_is_zero(self):
        entry = om.model_entry({"id": "a/b"})
        self.assertEqual(entry["cost"], {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0})


class TestSyncFourPlaces(unittest.TestCase):
    def base_config(self):
        return {
            "models": {"mode": "merge", "providers": {"other": {"baseUrl": "x"}}},
            "agents": {"defaults": {"models": {}, "modelPolicy": {"allow": []},
                                    "model": {"primary": "other/keep"}}},
        }

    def test_writes_all_four_places(self):
        cfg = self.base_config()
        entries = [om.model_entry({"id": "group/cheap-first"}),
                   om.model_entry({"id": "auto/glm-5.3"})]
        om.sync_four_places(cfg, entries)

        prov = cfg["models"]["providers"]["magpie"]
        self.assertEqual(prov["baseUrl"], "http://127.0.0.1:3425/v1")
        self.assertEqual(prov["apiKey"], "magpie")
        self.assertEqual(prov["api"], "openai-completions")
        self.assertEqual(len(prov["models"]), 2)

        d = cfg["agents"]["defaults"]
        self.assertIn("magpie/group/cheap-first", d["models"])
        self.assertIn("magpie/auto/glm-5.3", d["models"])
        self.assertIn("magpie/group/cheap-first", d["modelPolicy"]["allow"])
        self.assertIn("magpie/auto/glm-5.3", d["modelPolicy"]["allow"])

    def test_preserves_existing_config(self):
        cfg = self.base_config()
        cfg["agents"]["defaults"]["models"]["other/keep"] = {}
        cfg["agents"]["defaults"]["modelPolicy"]["allow"].append("other/keep")
        om.sync_four_places(cfg, [om.model_entry({"id": "group/g"})])

        d = cfg["agents"]["defaults"]
        self.assertIn("other/keep", d["models"])
        self.assertIn("other/keep", d["modelPolicy"]["allow"])
        self.assertIn("other", cfg["models"]["providers"])
        self.assertEqual(d["model"]["primary"], "other/keep")

    def test_is_idempotent(self):
        cfg = self.base_config()
        entries = [om.model_entry({"id": "group/g"})]
        om.sync_four_places(cfg, entries)
        first = len(cfg["agents"]["defaults"]["modelPolicy"]["allow"])
        om.sync_four_places(cfg, entries)
        second = len(cfg["agents"]["defaults"]["modelPolicy"]["allow"])
        self.assertEqual(first, second)
        self.assertEqual(len(cfg["models"]["providers"]["magpie"]["models"]), 1)

    def test_does_not_change_primary(self):
        cfg = self.base_config()
        om.sync_four_places(cfg, [om.model_entry({"id": "group/g"})])
        self.assertEqual(cfg["agents"]["defaults"]["model"]["primary"], "other/keep")


class TestWiredState(unittest.TestCase):
    def test_reports_unwired(self):
        st = om.wired_state({})
        self.assertFalse(st["provider"])
        self.assertEqual(st["models"], 0)

    def test_reports_fully_wired(self):
        cfg = {
            "models": {"providers": {"magpie": {
                "baseUrl": "http://127.0.0.1:3425/v1", "api": "openai-completions",
                "models": [{"id": "group/g"}]}}},
            "agents": {"defaults": {
                "models": {"magpie/group/g": {}},
                "modelPolicy": {"allow": ["magpie/group/g"]},
                "model": {"primary": "other/x"}}},
        }
        st = om.wired_state(cfg)
        self.assertTrue(st["provider"])
        self.assertEqual(st["models"], 1)
        self.assertEqual(st["in_registry"], 1)
        self.assertEqual(st["in_allow"], 1)

    def test_detects_missing_allow_entry(self):
        """The sneaky failure: provider and registry present, allow missing."""
        cfg = {
            "models": {"providers": {"magpie": {
                "baseUrl": "u", "api": "a", "models": [{"id": "group/g"}]}}},
            "agents": {"defaults": {
                "models": {"magpie/group/g": {}},
                "modelPolicy": {"allow": []},
                "model": {"primary": "other/x"}}},
        }
        st = om.wired_state(cfg)
        self.assertEqual(st["in_allow"], 0)
        self.assertNotEqual(st["in_allow"], st["models"])


class TestConfigPath(unittest.TestCase):
    def test_env_override(self):
        old = os.environ.get("OPENCLAW_CONFIG_PATH")
        os.environ["OPENCLAW_CONFIG_PATH"] = "/tmp/somewhere.json"
        try:
            # compare as Path objects: on Windows, Path("/tmp/x") normalises
            # to "\\tmp\\x", so a string comparison would fail there
            self.assertEqual(om.openclaw_config(), Path("/tmp/somewhere.json"))
        finally:
            if old is None:
                os.environ.pop("OPENCLAW_CONFIG_PATH", None)
            else:
                os.environ["OPENCLAW_CONFIG_PATH"] = old

    def test_default_path(self):
        old = os.environ.pop("OPENCLAW_CONFIG_PATH", None)
        try:
            self.assertEqual(
                om.openclaw_config(),
                Path.home() / ".openclaw" / "openclaw.json",
            )
        finally:
            if old is not None:
                os.environ["OPENCLAW_CONFIG_PATH"] = old


class TestJsonRoundTrip(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "openclaw.json"
            cfg = {"a": 1, "b": {"c": "x"}}
            om.write_config(p, cfg)
            self.assertEqual(om.read_config(p), cfg)
            # valid JSON on disk
            json.loads(p.read_text(encoding="utf-8"))


class TestWiredStatePrimaryShapes(unittest.TestCase):
    """`agents.defaults.model` is written both as an object and as a bare string.

    OpenClaw's gateway flips it to the string form when the default model is
    changed out of band (seen 2026-10-27 15:40:37). `doctor` must read both
    instead of dying with 'str' object has no attribute 'get'.
    """

    def cfg(self, model):
        return {
            "models": {"providers": {"magpie": {
                "baseUrl": "http://127.0.0.1:3425/v1",
                "apiKey": "magpie",
                "api": "openai-completions",
                "models": [{"id": "group/cheap-first"}],
            }}},
            "agents": {"defaults": {
                "models": {"magpie/group/cheap-first": {}},
                "modelPolicy": {"allow": ["magpie/group/cheap-first"]},
                "model": model,
            }},
        }

    def test_primary_as_object(self):
        st = om.wired_state(self.cfg({"primary": "other/x"}))
        self.assertEqual(st["primary"], "other/x")
        self.assertEqual(st["models"], 1)
        self.assertEqual(st["in_registry"], 1)
        self.assertEqual(st["in_allow"], 1)

    def test_primary_as_bare_string(self):
        st = om.wired_state(self.cfg("magpie/group/cheap-first"))
        self.assertEqual(st["primary"], "magpie/group/cheap-first")

    def test_primary_absent(self):
        self.assertIsNone(om.wired_state(self.cfg(None))["primary"])


if __name__ == "__main__":
    unittest.main()
