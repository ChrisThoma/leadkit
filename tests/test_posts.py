"""leads posts: the subs where you post an ad of your own (POST_SUBS), what
those posts did, and when each sub allows the next one.

    bin/test
"""
import sys, unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import posts, product, stats  # noqa: E402
from helpers import TempProduct  # noqa: E402


def own(pid, sub, title, body="", day="2026-11-13", score=1, comments=0, flair=None):
    stamp = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    return {"id": pid, "subreddit": sub, "title": title, "selftext": body, "created_utc": int(stamp),
            "score": score, "num_comments": comments, "link_flair_text": flair, "author": "MyDevAccount"}


STORE = "https://apps.apple.com/app/apple-store/id1000000003?ct=reddit_ipad"


class TempMossling(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("mossling")
        self.p = self.t.p
        self.p.cfg.POST_SUBS = {
            "ipadapps": {"flair": "Showcase"},
            "iosapps": {"flair": "💵 Paid", "every_days": 30, "not_before": "2026-12-10", "per_account": True},
            "terrariums": {"thread": "monthly self-promo megathread"},
        }

    def tearDown(self):
        self.t.close()
        product.Product("mossling")


class MineTest(TempMossling):
    def test_a_post_is_the_products_by_store_id_or_name(self):
        found = [own("a1", "ipadapps", "I made a tiny terrarium for my Home Screen", f"[App Store]({STORE})"),
                 own("a2", "ipad", "Knitwit: count rows without losing your place"),
                 own("a3", "iosapps", "Mossling, a calm terrarium")]
        self.assertEqual([x["id"] for x in posts.mine(self.p, found)], ["a1", "a3"])


class LogTest(TempMossling):
    def test_posts_are_logged_once_and_rechecked(self):
        posts.log(self.p, [own("a1", "ipadapps", "Mossling terrarium", score=2, comments=1, flair="Showcase")],
                  today="2026-11-14")
        posts.log(self.p, [own("a1", "ipadapps", "Mossling terrarium", score=13, comments=10)], today="2026-11-16")
        (r,) = posts.read(self.p)
        self.assertEqual((r["sub"], r["score"], r["comments"], r["checked"]), ("ipadapps", "13", "10", "2026-11-16"))
        self.assertEqual(r["posted"], "2026-11-13")
        self.assertEqual(r["flair"], "Showcase")  # kept when a later read has none
        self.assertEqual(r["url"], "https://www.reddit.com/r/ipadapps/comments/a1/")


class DueTest(TempMossling):
    def test_never_posted_is_due_now(self):
        d = {x["sub"]: x for x in posts.due(self.p, [], [], today=date(2026, 11, 16))}
        self.assertEqual(d["ipadapps"]["next"], "now")

    def test_every_days_and_not_before(self):
        logged = [{"sub": "iosapps", "posted": "2026-11-13", "score": "1", "comments": "1", "url": "u"}]
        d = {x["sub"]: x for x in posts.due(self.p, logged, [], today=date(2026, 11, 16))}
        self.assertEqual(d["iosapps"]["next"], "2026-12-13")
        self.assertEqual(d["iosapps"]["last"]["url"], "u")
        self.p.cfg.POST_SUBS["iosapps"]["every_days"] = 1
        d = {x["sub"]: x for x in posts.due(self.p, logged, [], today=date(2026, 11, 16))}
        self.assertEqual(d["iosapps"]["next"], "2026-12-10")

    def test_per_account_counts_other_apps_posts(self):
        # r/iosapps: once per developer per 30 days, whichever app it was for.
        others = [own("c1", "iosapps", "Tally Jar", day="2026-11-20")]
        d = {x["sub"]: x for x in posts.due(self.p, [], others, today=date(2026, 11, 21))}
        self.assertEqual(d["iosapps"]["next"], "2026-12-20")
        # but not for a sub without the rule
        others = [own("c2", "ipadapps", "Knitwit", day="2026-11-20")]
        d = {x["sub"]: x for x in posts.due(self.p, [], others, today=date(2026, 11, 21))}
        self.assertEqual(d["ipadapps"]["next"], "now")

    def test_no_cadence_after_a_post_says_so(self):
        logged = [{"sub": "ipadapps", "posted": "2026-11-13", "score": "13", "comments": "10", "url": "u"}]
        d = {x["sub"]: x for x in posts.due(self.p, logged, [], today=date(2026, 11, 16))}
        self.assertEqual(d["ipadapps"]["next"], "no limit recorded")

    def test_megathread_subs_are_reminders(self):
        d = {x["sub"]: x for x in posts.due(self.p, [], [], today=date(2026, 11, 16))}
        self.assertEqual(d["terrariums"]["next"], "comment in the monthly self-promo megathread")


class ReportTest(TempMossling):
    def test_report_lists_subs_and_open_app_threads(self):
        self.t.write("Reddit", [
            {"found": "2026-11-16", "subreddit": "buildinpublic", "kind": "app", "status": "new",
             "title": "What are you building this week?", "url": "https://www.reddit.com/r/buildinpublic/comments/x1/"},
            {"found": "2026-11-16", "subreddit": "buildinpublic", "kind": "app", "status": "skip",
             "title": "Old one", "url": "https://www.reddit.com/r/buildinpublic/comments/x2/"},
        ])
        found = [own("a1", "ipadapps", "terrarium", f"[Mossling]({STORE})", score=13, comments=10, flair="Showcase")]
        out = posts.report(self.p, fetch=lambda: found, today=date(2026, 11, 16))
        self.assertIn("r/ipadapps", out)
        self.assertIn("13 pts", out)
        self.assertIn("What are you building this week?", out)
        self.assertNotIn("Old one", out)

    def test_app_threads_past_three_days_are_left_out(self):
        self.t.write("Reddit", [{"found": "2026-11-08", "subreddit": "MacroStartups", "kind": "app", "status": "new",
                                 "title": "What are you building", "url": "https://www.reddit.com/r/M/comments/x3/"}])
        out = posts.report(self.p, fetch=None, today=date(2026, 11, 16))
        self.assertNotIn("What are you building", out)

    def test_per_account_offline_reads_every_products_log(self):
        logged = [{"sub": "iosapps", "posted": "2026-11-13", "url": "u"}]
        d = {x["sub"]: x for x in posts.due(self.p, [], logged, today=date(2026, 11, 16))}
        self.assertEqual(d["iosapps"]["next"], "2026-12-13")

    def test_offline_report_reads_the_log(self):
        posts.log(self.p, [own("a1", "ipadapps", "Mossling", score=13)], today="2026-11-16")
        out = posts.report(self.p, fetch=None, today=date(2026, 11, 16))
        self.assertIn("13 pts", out)

    def test_stats_shows_own_posts(self):
        posts.log(self.p, [own("a1", "ipadapps", "Mossling terrarium", score=13, comments=10)], today="2026-11-16")
        out = stats.report([self.p])
        self.assertIn("Own posts", out)
        self.assertIn("Mossling terrarium", out)


class ConfigTest(unittest.TestCase):
    def test_every_post_sub_uses_known_keys(self):
        for p in product.everything():
            for sub, rule in p.get("POST_SUBS", {}).items():
                self.assertLessEqual(set(rule), posts.KEYS, f"{p.name} r/{sub}")
                if "not_before" in rule:
                    date.fromisoformat(rule["not_before"])


if __name__ == "__main__":
    unittest.main()
