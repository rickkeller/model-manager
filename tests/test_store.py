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
        self.assertEqual(self.store.data["models"]["minimax-m2.7"]["model_id"], "ollama/minimax-m2.7:new")
        self.assertEqual(self.store.data["models"]["minimax-m2.7"]["health"], "unknown")
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("coding")])
        self.assertIn("minimax-m2.7", self.store.due())

    def test_a_changed_billing_leaves_ask_until_approved_again(self):
        self.store.import_snapshot({"minimax-m2.7": {**SNAPSHOT["minimax-m2.7"], "billing": "paid"}})
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
        self.assertEqual(advice["reason"], "current-down")
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

    def test_unknown_is_excluded_unless_requested(self):
        self.store.mark_health("minimax-m2.7", "unknown")
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("coding")])
        included = self.store.ask("coding", include_unknown=True)
        self.assertEqual(included[0]["name"], "minimax-m2.7")

    def test_a_later_import_replaces_pending_and_a_missing_model_is_not_approvable(self):
        self.store.import_snapshot({"minimax-m2.7": {**SNAPSHOT["minimax-m2.7"], "model_id": "ollama/minimax-m2.7:v3"}})
        self.store.import_snapshot({"minimax-m2.7": SNAPSHOT["minimax-m2.7"], "qwen3.5": SNAPSHOT["qwen3.5"]})
        row = self.store.data["models"]["minimax-m2.7"]
        self.assertNotIn("seen_model_id", row)
        self.assertIsNone(row.get("release"))
        self.assertEqual(self.store.data["models"]["qwen3-coder-next"]["status"], "missing")
        with self.assertRaises(Refused):
            self.store.approve("qwen3-coder-next")

    def test_a_provider_change_drops_approval(self):
        self.store.import_snapshot({"minimax-m2.7": {**SNAPSHOT["minimax-m2.7"], "provider": "other"}})
        self.assertEqual(self.store.data["models"]["minimax-m2.7"]["status"], "discovered")
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("fast")])

    def test_bad_rank_uses_and_smuggled_fields_are_refused_or_stripped(self):
        with self.assertRaises(Refused):
            self.store.import_snapshot({"bad": {**SNAPSHOT["qwen3.5"], "rank": "2"}})
        with self.assertRaises(Refused):
            self.store.import_snapshot({"bad": {**SNAPSHOT["qwen3.5"], "billing": "Free"}})
        with self.assertRaises(Refused):
            self.store.import_snapshot({"bad": {**SNAPSHOT["qwen3.5"], "uses": "coding"}})
        self.store.import_snapshot({"smuggled": {**SNAPSHOT["qwen3.5"], "health": "up", "release": "changed", "seen_model_id": "nope"}})
        row = self.store.data["models"]["smuggled"]
        self.assertEqual(row["health"], "unknown")
        self.assertNotIn("release", row)
        self.assertNotIn("seen_model_id", row)
        self.assertEqual(row["status"], "discovered")

    def test_unknown_schema_is_refused(self):
        path = Path(self.tmp.name, "registry.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema"] = 2
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(Refused):
            open_store(self.tmp.name)

    def test_parallel_imports_keep_every_row(self):
        from concurrent.futures import ThreadPoolExecutor
        root = self.tmp.name

        def add(index):
            store = open_store(root)
            store.import_snapshot({f"m{index}": {**SNAPSHOT["qwen3.5"], "model_id": f"example/{index}"}})

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(add, range(20)))
        store = open_store(root)
        self.assertTrue({f"m{index}" for index in range(20)} <= set(store.data["models"]))

    def test_read_does_not_create_a_registry_and_bad_input_is_clean(self):
        from model_manager.__main__ import main
        import io
        import contextlib
        missing = Path(self.tmp.name, "missing")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["--root", str(missing), "ask", "fast"])
        self.assertEqual(code, 2)
        self.assertFalse(missing.exists())
        self.assertIn("registry.json is missing", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_symlink_and_case_do_not_bypass_the_reserved_path(self):
        root = Path(self.tmp.name, "links")
        reserved = root / ".hermes"
        reserved.mkdir(parents=True)
        link = root / "alias"
        link.symlink_to(reserved, target_is_directory=True)
        with self.assertRaises(Refused):
            open_store(link)
        with self.assertRaises(Refused):
            open_store(root / ".Hermes" / "store")

    def test_both_down_is_said_and_fallback_must_differ_and_allow_the_use(self):
        self.store.mark_health("minimax-m2.7", "down")
        self.store.mark_health("qwen3.5", "down")
        advice = self.store.advise("jig-reasoning")
        self.assertIsNone(advice["suggested"])
        self.assertEqual(advice["reason"], "both-unavailable")
        with self.assertRaises(Refused):
            self.store.place("same", "slot", "minimax-m2.7", "minimax-m2.7", "fast")
        with self.assertRaises(Refused):
            self.store.place("wrong-use", "slot", "minimax-m2.7", "qwen3-coder-next", "fast")

    def test_due_includes_a_fallback_and_a_stale_check(self):
        self.assertIn("qwen3.5", self.store.due(max_age_seconds=-1))
        self.assertIn("minimax-m2.7", self.store.due(max_age_seconds=-1))
        self.assertNotIn("minimax-m2.7", [row["name"] for row in self.store.ask("fast", max_age_seconds=-1)])
