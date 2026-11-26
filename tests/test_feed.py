import json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

from leadkit import feed, study

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def post(author, c, hours_ago, text="a post long enough to count as the body", likes="2"):
    when = NOW.timestamp() - hours_ago * 3600
    return {"path": f"/@{author}/post/{c}", "date": datetime.fromtimestamp(when, timezone.utc).isoformat().replace("+00:00", "Z"),
            "lines": [author, f"{int(hours_ago)}h", text], "likes": likes, "replies": "1", "query": "for_you"}


class FeedReportTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.out, self.products = self.d / "feed", self.d / "products"
        self.out.mkdir()
        (self.products / "app" / "leads").mkdir(parents=True)
        (self.products / "app" / "leads" / "threads-leads.tsv").write_text(
            "found\turl\n2026-11-24\thttps://www.threads.com/@logged/post/LOGGED1\n")

    def dump(self, name, items):
        path = self.out / name
        path.write_text(json.dumps(items))
        return path

    def report(self, path, **kw):
        return feed.report(path, out=self.out, products_dir=self.products, now=NOW, **kw)

    def test_newest_first_and_leaves_out_mine_logged_and_old(self):
        path = self.dump("feed-2026-11-25.json", [
            post("older", "B", 5), post("newest", "A", 0.5), post(feed.ME, "MINE", 1),
            post("logged", "LOGGED1", 1), post("stale", "OLD", 72)])
        lines = self.report(path)
        heads = [l for l in lines if l.strip().startswith(("30m", "5h"))]
        self.assertEqual([h.split()[1] for h in heads], ["@newest", "@older"])
        self.assertEqual(lines[-1], "# 2 posts (left out: 1 mine, 1 logged, 1 old)")

    def test_posts_from_an_earlier_dump_are_left_out_unless_all(self):
        self.dump("feed-2026-11-24.json", [post("seen", "S", 20)])
        path = self.dump("feed-2026-11-25.json", [post("seen", "S", 21), post("fresh", "F", 1)])
        self.assertEqual(self.report(path)[-1], "# 1 posts (left out: 1 listed before)")
        self.assertEqual(self.report(path, everything=True)[-1], "# 2 posts")

    def test_link_and_text_are_printed(self):
        path = self.dump("feed-2026-11-25.json", [post("a", "X1", 2, text="what shortcuts do you use on your iPhone?")])
        lines = self.report(path)
        self.assertIn("      https://www.threads.com/@a/post/X1", lines)
        self.assertIn("      what shortcuts do you use on your iPhone?", lines)


class FeedScriptTest(unittest.TestCase):
    def test_feed_js_gathers_under_its_own_key_and_dump_reads_it(self):
        self.assertIn("sessionStorage.getItem('leadkitFeed')", feed.FEED_JS)
        self.assertNotIn("KEY", feed.FEED_JS)
        self.assertIn("getItem('leadkitFeed')", study.dump_js("http://127.0.0.1:1/", feed.KEY))
        self.assertIn("getItem('leadkitStudy')", study.dump_js("http://127.0.0.1:1/"))

    def test_code_reads_both_hosts(self):
        self.assertEqual(feed.code("https://www.threads.net/@a/post/Ab-1?x=1"), "Ab-1")
        self.assertIsNone(feed.code("https://www.threads.com/@a"))


if __name__ == "__main__":
    unittest.main()
