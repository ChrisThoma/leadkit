"""Reddit through Arctic Shift, with a fake `get` so nothing touches the network.

Reddit refuses anonymous search.rss, and its feeds allow one
request every 30 s or so. Arctic Shift's per-sub listing is close to live, so
a run lists each sub back to the cutoff and runs the product's search queries
locally over the posts.

    bin/test
"""
import sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import arctic, kinds, product, reddit  # noqa: E402
from helpers import TempProduct  # noqa: E402
from test_reddit import entry  # noqa: E402

NOW = int(time.time())


def post(pid, sub, title, body="", hours=1.0, author="someone"):
    return {"id": pid, "subreddit": sub, "title": title, "selftext": body, "author": author,
            "created_utc": NOW - int(hours * 3600), "num_comments": 0}


class MatchesTest(unittest.TestCase):
    """Reddit's query syntax as the product configs use it."""

    def test_or_alternatives(self):
        self.assertTrue(arctic.matches("app OR apps", "Any good app for this?"))
        self.assertFalse(arctic.matches("app OR apps", "Happy with my new shoes"))

    def test_words_in_one_alternative_all_have_to_appear(self):
        self.assertTrue(arctic.matches("training plan", "Need a plan for my training"))
        self.assertFalse(arctic.matches("training plan", "My training is going well"))

    def test_a_quoted_phrase_is_matched_whole(self):
        q = '"where to start" OR "training plan"'
        self.assertTrue(arctic.matches(q, "Not sure where to start"))
        self.assertFalse(arctic.matches(q, "Where should I start"))

    def test_a_word_matches_its_plural_but_not_inside_another_word(self):
        self.assertTrue(arctic.matches("exercises OR resource", "Free resources for theory?"))
        self.assertFalse(arctic.matches("SEND", "A godsend"))
        self.assertTrue(arctic.matches("send", "My first SEND outside"))

    def test_punctuated_terms(self):
        self.assertTrue(arctic.matches('cragbook OR "5.10a"', "Finally sent my first 5.10a"))
        self.assertTrue(arctic.matches('"ipad mini" apps', "Best apps for the iPad mini?"))


class PostsTest(unittest.TestCase):
    def test_pages_back_until_the_cutoff(self):
        since = NOW - 48 * 3600
        pages = [[post(f"a{i}", "climbing", "t", hours=i * 0.2) for i in range(100)],
                 [post(f"b{i}", "climbing", "t", hours=20 + i * 0.3) for i in range(100)]]
        asked = []

        def get(path, params):
            asked.append(params)
            return pages[len(asked) - 1]
        got = arctic.posts("climbing", since, get=get)
        self.assertEqual(len(asked), 2)
        self.assertEqual(asked[1]["before"], min(p["created_utc"] for p in pages[0]) + 1)
        # Posts older than the cutoff on the last page are dropped.
        self.assertEqual(len(got), 100 + sum(p["created_utc"] >= since for p in pages[1]))

    def test_a_short_page_is_the_last(self):
        calls = []

        def get(path, params):
            calls.append(1)
            return [post("x", "climbing", "t")]
        self.assertEqual(len(arctic.posts("climbing", NOW - 3600 * 24, get=get)), 1)
        self.assertEqual(len(calls), 1)

    def test_an_entry_has_the_rss_entry_shape(self):
        (e,) = arctic.posts("climbing", NOW - 86400, get=lambda path, params: [
            post("1xabc", "climbing", "Sit &amp; hang drills?", "body text", author="poster")])
        self.assertEqual(e["url"], "https://www.reddit.com/r/climbing/comments/1xabc/")
        self.assertEqual((e["author"], e["sub"], e["title"], e["body"]), ("poster", "climbing", "Sit & hang drills?", "body text"))
        self.assertEqual(e["posted"], e["stamp"][:10])
        self.assertAlmostEqual(reddit.age_hours(e["stamp"], reddit.datetime.now(reddit.timezone.utc)), 1.0, delta=0.1)


class WatchTest(unittest.TestCase):
    """reddit.watch with source="arctic"."""

    def setUp(self):
        self.t = TempProduct("cragbook")
        self.t.p.cfg.NEW_FEEDS = ["bouldering"]
        self.t.p.cfg.SUBREDDITS = ["bouldering", "climbing"]
        self.t.p.cfg.SEARCHES = ["training plan"]
        self.t.p.cfg.GROUPS = [{"name": "apps", "subreddits": ["iosapps"], "searches": ["climbing"]}]
        self.t.p.cfg.SITE_SEARCHES = ['"climbing log app"']
        self.t.p.cfg.APP_LEADS = False

    def tearDown(self):
        self.t.close()
        product.Product("cragbook")

    def run_with(self, by_sub, reddit_feeds=None):
        listed = []

        def get(path, params):
            listed.append(params["subreddit"])
            if isinstance(by_sub.get(params["subreddit"]), Exception):
                raise by_sub[params["subreddit"]]
            return by_sub.get(params["subreddit"], [])
        fetched = []

        def fetch(url, pause, agent=None):
            fetched.append(url)
            return (reddit_feeds or {}).get(url, b"<feed/>")
        rows = reddit.watch(self.t.p, dry_run=True, pause=0, fetch=fetch, arctic_get=get)
        return rows, listed, fetched

    def test_each_sub_is_listed_once_and_reddit_only_for_the_posted_check(self):
        _, listed, fetched = self.run_with({})
        self.assertEqual(sorted(listed), ["bouldering", "climbing", "iosapps"])
        self.assertTrue(all("/user/" in u for u in fetched), fetched)

    def test_a_search_sub_keeps_only_posts_matching_the_query(self):
        # Both score as leads; only m1 has every word of the query.
        rows, _, _ = self.run_with({"climbing": [post("m1", "climbing", "Plateaued at V4, need a training plan"),
                                                 post("m2", "climbing", "Plateaued at V4 and not improving. Any good apps?")]})
        self.assertEqual([r["url"] for r in rows], ["https://www.reddit.com/r/climbing/comments/m1/"])

    def test_a_new_feed_sub_keeps_every_post(self):
        rows, _, _ = self.run_with({"bouldering": [
            post("n1", "bouldering", "Plateaued at V4 and not improving. Any good apps?")]})
        self.assertEqual(len(rows), 1)

    def test_a_group_search_reads_the_groups_subs(self):
        rows, _, _ = self.run_with({"iosapps": [
            post("g1", "iosapps", "A climbing app to track my sends? Plateaued at V4.")]})
        self.assertEqual(len(rows), 1)

    def test_a_failed_listing_falls_back_to_the_subs_reddit_feed(self):
        feed = entry("climbing", "Plateaued at V4, need a training plan", "Not improving for a year.")
        new = "https://www.reddit.com/r/climbing/new.rss?limit=100"
        rows, _, fetched = self.run_with({"climbing": arctic.Error("down")}, {new: feed})
        self.assertIn(new, fetched)
        self.assertEqual(len(rows), 1)

    def test_site_wide_searches_are_skipped(self):
        _, _, fetched = self.run_with({})
        self.assertFalse([u for u in fetched if "search.rss" in u])

    def test_near_misses_are_appended_only_when_asked(self):
        # The hourly job asks: its triage reads near misses the way a pass does.
        self.t.write("Reddit", [])
        listing = {"bouldering": [post("w1", "bouldering", "Soft grades at my gym"),
                                  post("n1", "bouldering", "Plateaued at V4, need a training plan")]}
        get = lambda path, params: listing.get(params["subreddit"], [])
        fetch = lambda url, pause, agent=None: b"<feed/>"
        rows = reddit.watch(self.t.p, pause=0, fetch=fetch, arctic_get=get)
        self.assertEqual([r["url"][-4:] for r in rows], ["/n1/"])
        rows = reddit.watch(self.t.p, pause=0, fetch=fetch, arctic_get=get, near_misses=True)
        self.assertEqual([r["url"][-4:] for r in rows], ["/w1/"])
        self.assertTrue(rows[0]["notes"].startswith("Near miss [1]."))
        self.assertEqual([(r["url"][-4:], r["status"]) for r in self.t.read("Reddit")], [("/n1/", "new"), ("/w1/", "new")])

    def test_app_showcase_subs_are_listed_when_app_leads_are_on(self):
        self.t.p.cfg.APP_LEADS = True
        sub = kinds.APP["subreddits"][0]
        rows, listed, _ = self.run_with({sub: [post("s1", sub, "Weekly thread: share what you're building this week", hours=60)]})
        self.assertIn(sub, listed)
        self.assertEqual([r["kind"] for r in rows], ["app"])


class ThreadTest(unittest.TestCase):
    def test_flattens_the_comment_tree_in_reading_order(self):
        def c(cid, author, body, replies=""):
            return {"kind": "t1", "data": {"id": cid, "author": author, "body": body, "score": 2,
                                           "created_utc": NOW - 600, "replies": replies}}
        tree = [c("a", "one", "top", {"data": {"children": [c("b", "two", "reply")]}}),
                {"kind": "more", "data": {"children": ["x"]}},
                c("d", "three", "second top")]

        def get(path, params):
            return [post("1xabc", "climbing", "Title", "Body")] if path == "posts/ids" else tree
        t = arctic.thread("https://www.reddit.com/r/climbing/comments/1xabc/some_slug/", get=get)
        self.assertEqual(t["post"]["title"], "Title")
        self.assertEqual([(d, x["author"]) for d, x in t["comments"]], [(0, "one"), (1, "two"), (0, "three")])


if __name__ == "__main__":
    unittest.main()
