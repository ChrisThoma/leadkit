import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import allapps  # noqa: E402


class AllAppsTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(allapps.DATA.read_text())
        self.by_key = {v["key"]: allapps.reply(self.data, v) for v in self.data["variants"]}

    def test_every_app_is_linked_in_every_variant(self):
        for text in self.by_key.values():
            for a in self.data["apps"]:
                self.assertIn(f"[{a['name']}]({allapps.app_store(self.data, a['id'])})", text)
            self.assertNotIn("{link}", text)

    def test_duo_has_no_play_links_and_any_has_one_per_android_app(self):
        self.assertNotIn("play.google", self.by_key["duo"])
        self.assertEqual(self.by_key["any"].count("play.google"), sum(bool(a["play"]) for a in self.data["apps"]))

    def test_copy_rules(self):
        for text in self.by_key.values():
            for bad in ("—", " - ", "$"):
                self.assertNotIn(bad, text)

    def test_the_page_holds_both_replies(self):
        page = allapps.render(self.data)
        self.assertEqual(page.count("<article>"), 2)


if __name__ == "__main__":
    unittest.main()
