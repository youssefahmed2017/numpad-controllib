"""Tests for tools/nclib.py. Run: python -m unittest discover -s tests"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import nclib  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# each bad fixture, and words its error must contain
EXPECTED = {
    "wrong-format": "format must be",
    "newer-version": "newer than this library",
    "no-name": "profile.name: missing",
    "long-name": "at most 60 characters",
    "unknown-action": "unknown action 'teleport'",
    "unknown-key": "unknown key 'KP1'",
    "unknown-slot": "unknown slot 'triple'",
    "tap-only-key": "can only be tapped",
    "bad-press-keys": "unknown key 'banana'",
    "empty-type-text": "no text set",
    "bad-percent": "between 0 and 100",
    "turbo-range": "turbo must be",
    "extra-binding-field": "unknown field(s) ['colour']",
    "empty-macro": "the macro has no steps",
    "bad-macro-step": "can't be used as a macro step",
    "too-many-steps": "at most 30 steps",
    "if-mode-empty": "both branches empty",
    "bad-wait": "between 0 and 60 seconds",
    "exe-in-match": "without .exe",
    "no-keys": "sets no keys",
    "no-meta": "meta: missing",
    "bad-platform": "meta.platforms",
    "unknown-meta-field": "unknown field 'rating'",
}


class BadFixtures(unittest.TestCase):
    def test_every_fixture_has_an_expectation(self):
        names = {p.stem for p in (FIXTURES / "bad").glob("*.json")}
        self.assertEqual(names, set(EXPECTED))

    def test_each_fails_for_its_reason(self):
        for name, words in EXPECTED.items():
            with self.subTest(name):
                rep = nclib.check_file(FIXTURES / "bad" / f"{name}.json")
                self.assertTrue(rep.errors, f"{name} passed but should fail")
                self.assertTrue(any(words in e for e in rep.errors), f"{name}: {rep.errors}")


class GoodFiles(unittest.TestCase):
    def test_good_fixture_passes(self):
        rep = nclib.check_file(FIXTURES / "good" / "everything.json")
        self.assertEqual(rep.errors, [])
        self.assertIn("macro", rep.summary["risky_actions"])
        self.assertIn("press_keys", rep.summary["risky_actions"])   # found inside the macro

    def test_library_profiles_pass(self):
        paths = nclib.all_profiles()
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path.name):
                self.assertEqual(nclib.check_file(path).errors, [])

    def test_index_has_checksums_of_the_files(self):
        import hashlib
        index, _ = nclib.build_index()
        for e in index["profiles"]:
            raw = (nclib.ROOT / e["path"]).read_bytes()
            self.assertEqual(e["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(e["size"], len(raw))

    def test_catalog_draws_the_pad(self):
        index, _ = nclib.build_index()
        text = nclib.render_catalog(index)
        for e in index["profiles"]:
            self.assertIn(f"## {e['name']}", text)
        data = json.loads((nclib.ROOT / "profiles/official/discord.json").read_text(encoding="utf-8"))
        pad = nclib.keymap(data)
        self.assertIn("**7**<br>ctrl+shift+m", pad)
        self.assertEqual(pad.count("\n"), 6)   # header, rule, five rows

    def test_index_builds(self):
        # whether index.json is current is checked by CI on main only (PRs don't update it)
        index, failed = nclib.build_index()
        self.assertEqual(failed, [])
        self.assertEqual(index["count"], len(nclib.all_profiles()))


class KeyParsing(unittest.TestCase):
    def test_accepts(self):
        for text in ("ctrl+c", "Super + Q", "Down Down Enter", "ctrl+shift+F5", "alt+Left, Enter", "ctrl+grave"):
            with self.subTest(text):
                self.assertIsNone(nclib.keys_problem(text))

    def test_rejects(self):
        for text in ("", "ctrl+", "hyper+x", "F25"):
            with self.subTest(text):
                self.assertIsNotNone(nclib.keys_problem(text))


class SchemaInSync(unittest.TestCase):
    """profile.schema.json repeats some of actions.json for editors; keep the two the same."""

    def setUp(self):
        self.schema = json.loads((ROOT / "schema" / "profile.schema.json").read_text(encoding="utf-8"))

    def test_action_ids(self):
        self.assertEqual(set(self.schema["$defs"]["action_id"]["enum"]), set(nclib.T["by_id"]))

    def test_pad_keys(self):
        names = self.schema["$defs"]["layer"]["propertyNames"]["anyOf"][0]["enum"]
        self.assertEqual(names, nclib.T["pad_keys"])

    def test_non_step_actions(self):
        banned = set(self.schema["$defs"]["step"]["properties"]["action"]["allOf"][1]["not"]["enum"])
        self.assertEqual(banned, {a["id"] for a in nclib.T["actions"] if not a["step"]})


if __name__ == "__main__":
    unittest.main()
