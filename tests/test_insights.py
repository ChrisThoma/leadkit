import sys, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import insights  # noqa: E402

END = date(2026, 11, 20)


def app(days=56, posts=(), **per_day):
    """An app with `days` days of numbers ending at END. per_day maps a metric to a
    function of the day index from the end (0 = END), or a constant."""
    out = {}
    for i in range(days):
        d = (END - timedelta(i)).isoformat()
        out[d] = {k: (f(i) if callable(f) else f) for k, f in per_day.items()}
    for p in posts:
        out.setdefault(p["date"], {})
    return {"name": "Test", "days": out, "countries": {}, "posts": list(posts)}


def post(day, type_="Reel", ref=""):
    return {"date": day.isoformat() if isinstance(day, date) else day, "type": type_, "ref": ref}


class ChanceTest(unittest.TestCase):
    def test_small_or_close_counts_are_not_a_change(self):
        self.assertFalse(insights.counts_differ(17, 26), "a 35% fall on 43 downloads is chance")
        self.assertFalse(insights.counts_differ(6, 2), "too few to say anything")
        self.assertTrue(insights.counts_differ(301, 414))

    def test_rates_need_enough_views_and_two_standard_errors(self):
        self.assertFalse(insights.rates_differ(3, 30, 1, 30), "under MIN_VIEWS")
        self.assertTrue(insights.rates_differ(301, 2474, 414, 2374))
        self.assertFalse(insights.rates_differ(100, 1000, 104, 1000))


class InsightsTest(unittest.TestCase):
    def test_a_steady_app_says_nothing(self):
        self.assertEqual(insights.insights(app(impressions=100, page_views=20, downloads=2)), [])

    def test_page_views_doubling_is_an_up_line(self):
        a = app(impressions=200, page_views=lambda i: 20 if i < 14 else 10, downloads=1)
        lines = insights.insights(a)
        self.assertTrue(any(x["kind"] == "up" and x["text"].startswith("Product page views +100%") for x in lines), lines)

    def test_no_comparison_until_both_windows_are_in_the_data(self):
        a = app(days=20, impressions=lambda i: 200 if i < 14 else 10, page_views=10)
        self.assertFalse([x for x in insights.insights(a) if x["text"].startswith("Impressions")])

    def test_tap_through_falling_as_impressions_grow_is_a_tip_not_a_problem(self):
        a = app(impressions=lambda i: 600 if i < 14 else 200, page_views=lambda i: 60 if i < 14 else 40)
        tap = [x for x in insights.insights(a) if x["text"].startswith("Tap-through")]
        self.assertEqual(tap[0]["kind"], "tip")
        self.assertIn("impressions grew 200%", tap[0]["hint"])

    def test_a_browse_spike_says_maybe_featured(self):
        a = app(impressions=100, page_views=10, **{"pv:App Store browse": lambda i: 10 if i < 7 else 1})
        self.assertTrue(any("maybe featured" in x["text"] for x in insights.insights(a)))

    def test_problems_come_first(self):
        a = app(impressions=lambda i: 100 if i < 14 else 300, page_views=lambda i: 30 if i < 14 else 15,
                **{"pv:App Store browse": lambda i: 10 if i < 7 else 1})
        kinds = [x["kind"] for x in insights.insights(a)]
        self.assertEqual(kinds, sorted(kinds, key=insights.ORDER.get))
        self.assertEqual(kinds[0], "down")

    def test_the_best_post_day_is_named_but_not_against_launch_week(self):
        hot = END - timedelta(5)
        a = app(page_views=lambda i: 40 if i in (4, 5) else 10, posts=[post(hot, "Reel", "E1"), post(hot, "Short", "E1")])
        line = [x for x in insights.insights(a) if "took page views" in x["text"]]
        self.assertIn("a Reel, a Short took page views to 80", line[0]["text"])
        new = app(days=9, page_views=lambda i: 40 if i in (4, 5) else 0, posts=[post(hot, "Reel")])
        self.assertFalse([x for x in insights.insights(new) if "took page views" in x["text"]],
                         "the week before the post isn't in the data, so there's no usual to beat")


class WhatWorksTest(unittest.TestCase):
    def test_types_are_called_against_the_days_nothing_went_out(self):
        reels = [END - timedelta(i) for i in (3, 10, 17, 24, 31)]
        shorts = [END - timedelta(i) for i in (5, 12, 19, 26, 33)]
        lifted = {(END - d).days for d in reels} | {(END - d).days - 1 for d in reels}
        a = app(page_views=lambda i: 30 if i in lifted else 10,
                posts=[post(d, "Reel") for d in reels] + [post(d, "Short") for d in shorts] + [post(END - timedelta(40), "TikTok")])
        w = insights.what_works([a])
        by = {r["type"]: r for r in w["rows"]}
        self.assertEqual(by["Reel"]["call"], "keep")
        self.assertEqual(by["Short"]["call"], "weak")
        self.assertEqual(by["TikTok"]["call"], "too few")
        self.assertEqual(w["rows"][0]["type"], "Reel", "best first")
        self.assertEqual(w["rows"][-1]["type"], "TikTok", "too few last")
        self.assertEqual(by["Reel"]["alone"], 5)
        self.assertGreater(w["baseline"]["days"], 20)

    def test_a_post_on_the_last_day_waits_for_the_day_after(self):
        a = app(page_views=10, posts=[post(END, "Reel")])
        self.assertEqual(insights.what_works([a])["rows"], [])


if __name__ == "__main__":
    unittest.main()
