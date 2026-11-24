"""leads stats: the found -> drafted -> posted funnel, from the leads TSVs alone.

    bin/test
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import drafts, product, stats  # noqa: E402
from helpers import TempProduct  # noqa: E402


class OutcomeTest(unittest.TestCase):
    def test_each_row_gets_one_outcome(self):
        cases = [
            ({"status": "posted"}, "posted"),
            ({"status": "replied"}, "posted"),
            ({"status": "new"}, "open"),
            ({"status": "draft", "reply": "hi"}, "open"),
            ({"status": ""}, "open"),
            ({"status": "skip"}, "triage skip"),
            ({"status": "skip", "reply": "hi"}, "draft dropped"),
            ({"status": "skip", "reply": "hi", "notes": f"x {drafts.SKIP_NOTE} Reason: Not now."}, "you skipped"),
            ({"status": "skip", "reply": "hi", "notes": "Cleared 2026-11-01: thread over 3 days old, not posted."},
             "expired"),
            ({"status": "skip", "notes": "Never triaged; stale by 2026-10-16. Watcher [6]."}, "untriaged"),
        ]
        for row, want in cases:
            self.assertEqual(stats.outcome(row), want, row)

    def test_drafted_means_a_reply_was_written(self):
        self.assertTrue(stats.drafted({"status": "skip", "reply": "hi"}))
        self.assertTrue(stats.drafted({"status": "posted", "reply": ""}))  # posted by hand counts
        self.assertFalse(stats.drafted({"status": "skip", "reply": " "}))

    def test_watcher_score_band(self):
        self.assertEqual(stats.band({"notes": "Rules unchecked. Watcher [5]. body"}), "5")
        self.assertEqual(stats.band({"notes": "Watcher [7]."}), "6-7")
        self.assertEqual(stats.band({"notes": "Watcher [9]."}), "8-9")
        self.assertEqual(stats.band({"notes": "Watcher [14]."}), "10+")
        self.assertEqual(stats.band({"notes": "found by hand"}), "no score")

    def test_week_is_the_monday(self):
        self.assertEqual(stats.week({"found": "2026-11-16"}), "2026-11-16")  # a Monday
        self.assertEqual(stats.week({"found": "2026-11-15"}), "2026-11-09")
        self.assertEqual(stats.week({"found": ""}), "no date")

    def test_skip_reasons_from_the_drafts_page(self):
        rows = [{"notes": f"{drafts.SKIP_NOTE} Reason: Not now."},
                {"notes": f"a {drafts.SKIP_NOTE} Reason: Not now."},
                {"notes": f"{drafts.SKIP_NOTE}"},
                {"notes": "Skip: off topic"}]
        self.assertEqual(stats.reasons(rows), {"Not now": 2, "(none given)": 1})


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")
        self.t.write("Reddit", [
            {"found": "2026-11-10", "subreddit": "climbing", "url": "u1", "status": "posted", "reply": "a",
             "notes": "Comment: x Watcher [10]."},
            {"found": "2026-11-10", "subreddit": "climbing", "url": "u2", "status": "skip", "notes": "Watcher [5]."},
            {"found": "2026-11-11", "subreddit": "bouldering", "url": "u3", "status": "skip", "notes": "Watcher [5]."},
            {"found": "2026-11-03", "subreddit": "bouldering", "url": "u4", "status": "skip", "reply": "b",
             "notes": f"{drafts.SKIP_NOTE} Reason: Not now."},
        ])
        self.t.write("Threads", [{"found": "2026-11-12", "url": "t1", "status": "posted", "kind": "app"}])

    def tearDown(self):
        self.t.close()
        product.Product("cragbook")

    def test_funnel_by_platform_and_kind(self):
        out = stats.report([self.t.p])
        self.assertIn("Reddit domain", out)
        self.assertIn("Threads app", out)
        line = next(l for l in out.splitlines() if l.strip().startswith("Reddit domain"))
        # found 4, drafted 2, posted 1
        self.assertEqual(line.split()[2:5], ["4", "2", "1"])

    def test_subs_that_never_drafted_are_listed(self):
        out = stats.report([self.t.p], min_found=1)
        self.assertIn("r/climbing", out)
        self.assertIn("r/bouldering", out)

    def test_since_drops_older_rows(self):
        out = stats.report([self.t.p], since="2026-11-10")
        line = next(l for l in out.splitlines() if l.strip().startswith("Reddit domain"))
        self.assertEqual(line.split()[2:5], ["3", "1", "1"])
        self.assertNotIn("Not now", out)

    def test_score_bands_and_reasons_show(self):
        out = stats.report([self.t.p])
        self.assertIn("10+", out)
        self.assertIn("Not now", out)

    def test_every_real_product_reports(self):
        # Every configured product's TSVs: no crash on their quirks (old-style priorities, blank kinds).
        for p in product.everything():
            self.assertIn(p.title, stats.report([p]))


if __name__ == "__main__":
    unittest.main()
