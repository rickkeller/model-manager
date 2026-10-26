import json
import tempfile
import unittest
from pathlib import Path

from model_manager.store import Refused, open_store

SNAPSHOT = {
    "minimax-m2.7": {
        "provider": "ollama_cloud",
        "model_id": "ollama/minimax-m2.7:cloud",
        "billing": "free",
        "uses": ["fast", "coding"],
        "rank": 1,
    },
    "qwen3-coder-next": {
        "provider": "ollama_cloud",
        "model_id": "ollama/qwen3.5:cloud",
        "billing": "free",
        "uses": ["coding"],
        "rank": 2,
    },
    "qwen3.5": {
        "provider": "ollama_cloud",
        "model_id": "ollama/qwen3.5:cloud",
        "billing": "free",
        "uses": ["fast", "writing"],
        "rank": 3,
    },
}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = open_store(self.tmp.name)
        self.store.import_snapshot(SNAPSHOT)
        for name in SNAPSHOT:
            self.store.approve(name)
            self.store.mark_health(name, "up")
        self.store.place("jig-reasoning", "jig reasoning_model", "minimax-m2.7", "qwen3.5", "fast")
        self.store.place("bookrunner", "bookrunner config", "qwen3-coder-next", "minimax-m2.7", "coding")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ask_prefers_free_and_skips_a_down_model(self):
        self.assertEqual(self.store.ask("coding")[0]["name"], "minimax-m2.7")
        self.store.mark_health("minimax-m2.7", "down", "rate limit")
        self.assertEqual(self.store.ask("coding")[0]["name"], "qwen3-coder-next")

    def test_a_new_release_is_not_used(self):
        added = self.store.import_snapshot({"deepseek-v4-pro-ollama-cloud": {"provider": "ollama_cloud", "model_id": "ollama/deepseek-v4-pro:cloud", "billing": "free", "uses": ["reasoning"], "rank": 1}})
        self.assertEqual(added, ["deepseek-v4-pro-ollama-cloud"])
        self.assertEqual(self.store.ask("reasoning"), [])

    def test_a_changed_release_leaves_ask_until_approved_again(self):
        self.store.import_snapshot({"minimax-m2.7": {"provider": "ollama_cloud", "model_id": "ollama/minimax-m2.7:new", "billing": "free", "uses": ["fast", "coding"], "rank": 1}})
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("coding")])
        self.assertIn("minimax-m2.7", self.store.due())
        self.store.approve("minimax-m2.7")
        self.assertEqual(self.store.ask("coding")[0]["model_id"], "ollama/minimax-m2.7:new")
        self.assertEqual(self.store.data["models"]["minimax-m2.7"]["health"], "unknown")
        self.assertIn("minimax-m2.7", self.store.due())

    def test_a_changed_billing_leaves_ask_until_approved_again(self):
        self.store.import_snapshot({"minimax-m2.7": {"provider": "ollama_cloud", "model_id": "ollama/minimax-m2.7", "billing": "paid", "uses": ["fast", "coding"], "rank": 1}})
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("coding")])
        self.store.approve("minimax-m2.7")
        adopted = next(row for row in self.store.ask("coding") if row["name"] == "minimax-m2.7")
        self.assertEqual(adopted["billing"], "paid")

    def test_save_replaces_the_registry(self):
        self.store.save()
        text = Path(self.tmp.name, "registry.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(text)["models"]["minimax-m2.7"]["status"], "approved")
        self.assertEqual(list(Path(self.tmp.name).glob(".registry-*.tmp")), [])

    def test_advise_names_the_place_and_does_not_write_it(self):
        self.store.mark_health("minimax-m2.7", "down", "rate limit")
        advice = self.store.advise("jig-reasoning")
        self.assertEqual(advice["where"], "jig reasoning_model")
        self.assertEqual(advice["suggested"], "qwen3.5")
        self.assertFalse(Path(self.tmp.name, "jig").exists())

    def test_hermes_path_is_refused(self):
        with self.assertRaises(Refused):
            open_store("/tmp/model-manager-test/.hermes/store")

    def test_cli_ask(self):
        from model_manager.__main__ import main
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["--root", self.tmp.name, "ask", "fast"]), 0)
        self.assertEqual(json.loads(buf.getvalue())[0]["model_id"], "ollama/minimax-m2.7:cloud")
