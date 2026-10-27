"""Unit tests for magpie_bridge.

These run without a gateway and without magpie installed — they cover the pure
functions: model selection, path resolution, and the YAML/TOML writers.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import magpie_bridge as mb  # noqa: E402


class TestModelSelection(unittest.TestCase):
    def test_picks_groups_and_auto_by_default(self):
        models = [
            {"id": "group/cheap-first"},
            {"id": "auto/glm-5.3"},
            {"id": "volcengine/doubao-seed-evolving"},
            {"id": "openrouter/openai/gpt-6.1-terra-pro"},
        ]
        picked = mb.pick_models(models, None)
        ids = [m["id"] for m in picked]
        self.assertIn("group/cheap-first", ids)
        self.assertIn("auto/glm-5.3", ids)
        # bare provider/model ids are excluded: their model part may contain
        # slashes, which is ambiguous for provider/model agents
        self.assertNotIn("openrouter/openai/gpt-6.1-terra-pro", ids)

    def test_explicit_pattern_filters(self):
        models = [{"id": "group/cheap-first"}, {"id": "auto/glm-5.3"}]
        picked = mb.pick_models(models, "glm")
        self.assertEqual([m["id"] for m in picked], ["auto/glm-5.3"])

    def test_pattern_matches_substring(self):
        models = [{"id": "group/a"}, {"id": "auto/b"}]
        self.assertEqual(len(mb.pick_models(models, "group")), 1)


class TestPathResolution(unittest.TestCase):
    def test_specs_have_at_least_one_path(self):
        for name, spec in mb.agent_specs().items():
            self.assertTrue(spec.get("paths"), f"{name} has no path")
            self.assertIn(spec["format"], {"json", "jsonc", "yaml", "toml"},
                          f"{name} has an unknown format")

    def test_resolve_returns_absolute(self):
        for name, spec in mb.agent_specs().items():
            p = mb.resolve_agent_path(spec)
            self.assertTrue(p.is_absolute(), f"{name} resolved to a relative path")

    def test_every_platform_resolves(self):
        """Every agent must resolve on all three platforms."""
        specs = mb.agent_specs()
        for name, spec in specs.items():
            paths = spec["paths"]
            for plat in ("macos", "windows", "linux"):
                rel = paths.get(plat) or paths.get("home") or paths.get("xdg")
                self.assertIsNotNone(rel, f"{name} has no path for {plat}")

    def test_known_agents_present(self):
        specs = mb.agent_specs()
        for name in ("hermes", "claude", "codex", "gemini", "opencode", "qwen",
                     "dsh", "goose", "zed", "crush", "cursor", "copilot"):
            self.assertIn(name, specs)


class TestYamlWriter(unittest.TestCase):
    def test_creates_nested_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yaml"
            mb.yaml_set(p, "env.ANTHROPIC_BASE_URL", "http://127.0.0.1:3425")
            text = p.read_text()
            self.assertIn("env:", text)
            self.assertIn("ANTHROPIC_BASE_URL:", text)
            self.assertIn("127.0.0.1:3425", text)

    def test_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yaml"
            p.write_text("# a comment\nmodel: gpt-4\n")
            mb.yaml_set(p, "env.KEY", "value")
            text = p.read_text()
            self.assertIn("# a comment", text)
            self.assertIn("model: gpt-4", text)
            self.assertIn("KEY: value", text)

    def test_updates_existing_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.yaml"
            p.write_text("env:\n  KEY: old\n")
            mb.yaml_set(p, "env.KEY", "new")
            text = p.read_text()
            self.assertIn("KEY: new", text)
            self.assertNotIn("KEY: old", text)


class TestTomlWriter(unittest.TestCase):
    def test_creates_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            mb.toml_set(p, "model_providers.magpie.base_url", "http://127.0.0.1:3425/v1")
            text = p.read_text()
            self.assertIn("[model_providers.magpie]", text)
            self.assertIn("base_url = ", text)

    def test_preserves_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text('notify = ["x"]\n\n[other]\nkey = 1\n')
            mb.toml_set(p, "model_providers.magpie.base_url", "http://x")
            text = p.read_text()
            self.assertIn("notify = ", text)
            self.assertIn("[other]", text)
            self.assertIn("key = 1", text)

    def test_updates_existing_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("[t]\nkey = old\n")
            mb.toml_set(p, "t.key", "new")
            text = p.read_text()
            self.assertIn("key = \"new\"", text)
            self.assertNotIn("key = old", text)


class TestJsonWriter(unittest.TestCase):
    def test_nested_set(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            mb.json_set(p, "provider.magpie.options.baseURL", "http://x")
            data = json.loads(p.read_text())
            self.assertEqual(data["provider"]["magpie"]["options"]["baseURL"], "http://x")

    def test_preserves_siblings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"keep": 1, "provider": {"other": 2}}))
            mb.json_set(p, "provider.magpie.apiKey", "magpie")
            data = json.loads(p.read_text())
            self.assertEqual(data["keep"], 1)
            self.assertEqual(data["provider"]["other"], 2)
            self.assertEqual(data["provider"]["magpie"]["apiKey"], "magpie")


class TestBackup(unittest.TestCase):
    def test_backup_creates_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text("{}")
            b = mb.backup(p)
            self.assertIsNotNone(b)
            self.assertTrue(b.exists())
            self.assertEqual(b.read_text(), "{}")

    def test_backup_of_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(mb.backup(Path(d) / "nope.json"))


class TestScalars(unittest.TestCase):
    def test_yaml_scalar_quotes_when_needed(self):
        self.assertEqual(mb._yaml_scalar("plain"), "plain")
        self.assertTrue(mb._yaml_scalar("has: colon").startswith('"'))
        self.assertEqual(mb._yaml_scalar(True), "true")
        self.assertEqual(mb._yaml_scalar(42), "42")

    def test_toml_value(self):
        self.assertEqual(mb._toml_value("x"), '"x"')
        self.assertEqual(mb._toml_value(True), "true")
        self.assertEqual(mb._toml_value(["a", "b"]), '["a", "b"]')


if __name__ == "__main__":
    unittest.main()
