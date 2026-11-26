import gzip, json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import analytics, dashboard  # noqa: E402

DISC_HEAD = "Date\tApp Name\tApp Apple Identifier\tEvent\tPage Type\tSource Type\tEngagement Type\tDevice\tPlatform Version\tTerritory\tCounts\tUnique Counts"
DL_HEAD = "Date\tApp Name\tApp Apple Identifier\tDownload Type\tApp Version\tDevice\tPlatform Version\tSource Type\tPage Type\tPre-Order\tTerritory\tCounts"


def disc(date, event, n, src="App Store search", terr="US", unique=None):
    return f"{date}\tKnitwit\t1\t{event}\tNo page\t{src}\t\tiPhone\tiOS 26\t{terr}\t{n}\t{unique if unique is not None else n}"


def dl(date, kind, n, src="App Store search", terr="US"):
    return f"{date}\tKnitwit\t1\t{kind}\t1.0\tiPhone\tiOS 26\t{src}\tProduct page\t\t{terr}\t{n}"


class RawFiles:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp())

    def put(self, kind, name, head, lines):
        path = self.root / "1" / kind / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(("\n".join([head] + lines) + "\n").encode()))

    def close(self):
        shutil.rmtree(self.root)


class RowsTest(unittest.TestCase):
    """Apple's daily files repeat the three days before them with the same numbers,
    so adding them up would count most days three times."""

    def setUp(self):
        self.raw = RawFiles()

    def tearDown(self):
        self.raw.close()

    def total(self, metric, day):
        return sum(c for (d, m, *_), (c, u) in analytics.rows("1", self.raw.root).items() if d == day and m == metric)

    def test_a_day_restated_in_later_files_counts_once(self):
        self.raw.put("discovery", "ongoing-2026-11-02.tsv.gz", DISC_HEAD, [disc("2026-11-01", "Impression", 5)])
        self.raw.put("discovery", "ongoing-2026-11-03.tsv.gz", DISC_HEAD,
                     [disc("2026-11-01", "Impression", 5), disc("2026-11-02", "Impression", 7)])
        self.assertEqual(self.total("impressions", "2026-11-01"), 5)
        self.assertEqual(self.total("impressions", "2026-11-02"), 7)

    def test_the_newest_file_wins_a_revised_day(self):
        self.raw.put("discovery", "ongoing-2026-11-02.tsv.gz", DISC_HEAD, [disc("2026-11-01", "Impression", 5)])
        self.raw.put("discovery", "ongoing-2026-11-04.tsv.gz", DISC_HEAD, [disc("2026-11-01", "Impression", 6)])
        self.assertEqual(self.total("impressions", "2026-11-01"), 6)

    def test_snapshot_fills_the_days_before_the_ongoing_files(self):
        self.raw.put("discovery", "snapshot-2026-10-30.tsv.gz", DISC_HEAD,
                     [disc("2026-10-01", "Impression", 3), disc("2026-10-29", "Impression", 4)])
        self.raw.put("discovery", "ongoing-2026-10-31.tsv.gz", DISC_HEAD, [disc("2026-10-29", "Impression", 4)])
        self.assertEqual(self.total("impressions", "2026-10-01"), 3)
        self.assertEqual(self.total("impressions", "2026-10-29"), 4)

    def test_rows_in_one_file_for_one_day_add_up(self):
        self.raw.put("discovery", "ongoing-2026-11-02.tsv.gz", DISC_HEAD,
                     [disc("2026-11-01", "Page view", 2, terr="US"), disc("2026-11-01", "Page view", 3, terr="DE")])
        self.assertEqual(self.total("page_views", "2026-11-01"), 5)

    def test_updates_and_restores_are_not_downloads(self):
        self.raw.put("downloads", "ongoing-2026-11-02.tsv.gz", DL_HEAD, [
            dl("2026-11-01", "First-time download", 2), dl("2026-11-01", "Redownload", 1),
            dl("2026-11-01", "Auto-update", 9), dl("2026-11-01", "Restore", 4)])
        self.assertEqual(self.total("downloads", "2026-11-01"), 2)
        self.assertEqual(self.total("redownloads", "2026-11-01"), 1)


class SegmentsTest(unittest.TestCase):
    def test_segments_join_under_one_header(self):
        text = analytics.join_segments(["H\na\n", "H\nb\n"])
        self.assertEqual(text, "H\na\nb\n")


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.raw = RawFiles()
        self.raw.put("downloads", "ongoing-2026-11-02.tsv.gz", DL_HEAD, [
            dl("2026-11-01", "First-time download", 2, src="App Store search"),
            dl("2026-11-01", "First-time download", 1, src="Institutional purchase")])
        self.raw.put("discovery", "ongoing-2026-11-02.tsv.gz", DISC_HEAD,
                     [disc("2026-11-01", "Page view", 9, unique=4)])

    def tearDown(self):
        self.raw.close()

    def data(self, sales=(), posts=()):
        return dashboard.app_data("1", "Knitwit: Row Counter", ["Knitwit"], list(sales), list(posts), self.raw.root)

    def test_small_sources_fold_into_other(self):
        day = self.data()["days"]["2026-11-01"]
        self.assertEqual(day["dl:App Store search"], 2)
        self.assertEqual(day["dl:Other"], 1)
        self.assertEqual(day["downloads"], 3)

    def test_page_views_are_unique_devices(self):
        self.assertEqual(self.data()["days"]["2026-11-01"]["page_views"], 4)

    def test_sales_and_posts_join_by_app_name(self):
        a = self.data(sales=[{"date": "2026-11-01", "app": "Knitwit", "store": "Play", "units": "2"},
                             {"date": "2026-11-01", "app": "Cragbook", "store": "iOS", "units": "5"}],
                      posts=[{"date": "2026-11-03", "app": "Knitwit", "channel": "YouTube", "ref": "E9"},
                             {"date": "2026-11-03", "app": "Mossling", "channel": "Threads", "ref": ""}])
        self.assertEqual(a["days"]["2026-11-01"]["units_play"], 2)
        self.assertNotIn("units_ios", a["days"]["2026-11-01"])
        self.assertEqual([p["ref"] for p in a["posts"]], ["E9"])
        self.assertIn("2026-11-03", a["days"], "a post day is on the axis even with no numbers yet")

    def test_each_post_gets_a_type(self):
        t = dashboard.post_type
        self.assertEqual(t("YouTube", "https://youtube.com/shorts/x"), "Short")
        self.assertEqual(t("YouTube", "https://www.youtube.com/watch?v=x"), "YouTube video")
        self.assertEqual(t("Instagram", "https://www.instagram.com/u/reel/x/"), "Reel")
        self.assertEqual(t("Threads video", ""), "Threads post")
        self.assertEqual(t("Reddit r/knittinghelp", ""), "Reddit post")
        self.assertEqual(t("Product Hunt", ""), "Launch")

    def test_posted_replies_come_from_the_leads_files(self):
        rows = {"reddit": [
                    {"found": "2026-11-19", "posted": "2026-11-20", "subreddit": "knitting", "title": "How did you learn cables?",
                     "url": "https://www.reddit.com/r/knitting/comments/a/", "status": "posted", "kind": "domain"},
                    {"found": "2026-10-25", "posted": "", "subreddit": "knitting", "title": "Undated",
                     "url": "https://www.reddit.com/r/knitting/comments/b/", "status": "posted", "kind": "app"},
                    {"found": "2026-11-19", "posted": "", "subreddit": "knitting", "title": "Skipped",
                     "url": "u3", "status": "skipped", "kind": ""}],
                "threads": [{"found": "2026-11-01", "posted": "2026-11-02", "author": "someone", "url": "t1",
                             "status": "replied", "kind": "app"}]}
        out = dashboard.replies(rows)
        self.assertEqual([(r["date"], r["type"], r["title"]) for r in out], [
            ("2026-10-25", "Reddit reply", "Undated"), ("2026-11-02", "Threads reply", "@someone"),
            ("2026-11-20", "Reddit reply", "How did you learn cables?")])
        self.assertEqual(out[0]["channel"], "r/knitting")
        self.assertEqual(out[0]["about"], "found", "no posted date: the day it was found stands in")
        self.assertEqual((out[2]["mentions"], out[0]["mentions"]), ("", "app"))

    def test_own_reddit_posts_are_posts_with_their_score(self):
        out = dashboard.own_reddit([{"posted": "2026-11-19", "sub": "knitting", "title": "My first sock, finally done",
                                     "url": "https://www.reddit.com/r/knitting/comments/1/", "score": "3", "comments": "1"}])
        self.assertEqual(out[0]["type"], "Reddit post")
        self.assertEqual((out[0]["channel"], out[0]["likes"], out[0]["replies"]), ("r/knitting", "3", "1"))

    def test_extra_posts_join_without_repeating_a_logged_url(self):
        a = dashboard.app_data("1", "Knitwit: Row Counter", ["Knitwit"], [], [
            {"date": "2026-11-03", "app": "Knitwit", "channel": "Reddit r/knitting", "ref": "",
             "url": "https://www.reddit.com/r/knitting/comments/1/", "note": "Logged"}], self.raw.root, extra=[
            {"date": "2026-11-03", "type": "Reddit post", "channel": "r/knitting", "title": "Own",
             "url": "https://www.reddit.com/r/knitting/comments/1/"},
            {"date": "2026-11-04", "type": "Reddit reply", "channel": "r/x", "title": "A reply", "url": "r2"}])
        self.assertEqual([(p["date"], p["type"], p["title"]) for p in a["posts"]],
                         [("2026-11-03", "Reddit post", "Logged"), ("2026-11-04", "Reddit reply", "A reply")])

    def test_lift_compares_two_days_with_two_usual_days(self):
        days = {f"2026-11-0{i}": {"page_views": 10} for i in range(1, 8)}
        days["2026-11-08"] = {"page_views": 50}
        days["2026-11-09"] = {"page_views": 30}
        self.assertEqual(dashboard.lift(days, "2026-11-08"), (80, 20))

    def test_waiting_lists_leadkit_apps_with_no_report_yet(self):
        # A new app's first report comes a day or two after the request.
        app_list = [("1", "Knitwit: Row Counter"), ("9", "Mossling: Moss Care"), ("5", "Other App: Not In Leadkit")]
        out = dashboard.waiting(app_list, shown={"1"}, apps=["Knitwit", "Mossling"])
        self.assertEqual(out, [{"id": "9", "name": "Mossling", "title": "Mossling: Moss Care"}])

    def test_projection_of_a_steady_month_is_that_month(self):
        pr = dashboard.projection([2.0] * 60)
        self.assertEqual(pr["days"][:3], [2.0, 2.0, 2.0])
        self.assertEqual(pr["sd"], 0)

    def test_a_trend_runs_two_weeks_then_holds(self):
        pr = dashboard.projection([float(i) for i in range(60)], horizon=60)
        self.assertGreater(pr["days"][10], pr["days"][0], "rising sales project rising")
        self.assertEqual(pr["days"][13], pr["days"][59], "and level off after 14 days")

    def test_one_launch_day_does_not_set_the_level(self):
        values = [2.0] * 59 + [40.0]
        self.assertLess(dashboard.projection(values)["days"][0], 3)

    def test_a_falling_trend_stops_at_zero(self):
        pr = dashboard.projection([float(60 - i) for i in range(60)], horizon=92)
        self.assertEqual(min(pr["days"]), 0.0)

    def test_sales_projection_fills_days_with_no_sales(self):
        sales = [{"date": "2026-10-01", "units": "1", "proceeds": "0.70"},
                 {"date": "2026-10-28", "units": "1", "proceeds": "0.70"}]
        pr = dashboard.sales_projection(sales, "2026-10-28")
        self.assertEqual(pr["from"], "2026-10-29")
        self.assertAlmostEqual(pr["p"]["days"][0], 0.70 / 21, delta=0.05,
                               msg="two sales in four weeks is about 3 cents a day, not 84")

    def test_each_store_gets_its_own_projection(self):
        sales = [{"date": f"2026-10-{d:02}", "store": st, "units": n, "proceeds": n, "sales": n}
                 for d in range(1, 29) for st, n in (("iOS", "3"), ("Play", "1"))]
        pr = dashboard.store_projections(sales, "2026-10-28")
        self.assertEqual(pr["u"]["days"][0], 4.0, "the top level is both stores")
        self.assertEqual(pr["stores"]["iOS"]["u"]["days"][0], 3.0)
        self.assertEqual(pr["stores"]["Play"]["u"]["days"][0], 1.0)
        self.assertEqual(pr["stores"]["Play"]["from"], pr["from"])

    def test_no_sales_has_no_store_projections(self):
        self.assertIsNone(dashboard.store_projections([], ""))

    def test_page_embeds_the_data(self):
        html = dashboard.render({"built": "2026-11-21", "apps": [], "sources": []})
        self.assertIn('const DATA = {"built":"2026-11-21"', html)



class RestartTest(unittest.TestCase):
    """The dashboard's Restart button starts a fresh server on the same port, without Chrome."""

    def test_restart_command(self):
        cmd = dashboard.restart_command(8419)
        self.assertEqual(cmd[1:], ["-m", "leadkit.cli", "dashboard", "--no-open", "--port", "8419"])
        self.assertEqual(cmd[0], sys.executable)


class StaleServerTest(unittest.TestCase):
    """A server left running serves the old code, so the page says when the code on disk is newer than the server."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "leadkit" / "data").mkdir(parents=True)
        self.py = self.root / "leadkit" / "dashboard.py"
        self.html = self.root / "leadkit" / "data" / "dashboard.html"
        for f in (self.py, self.html):
            f.write_text("x")

    def touch(self, f, t):
        import os
        os.utime(f, (t, t))

    def test_nothing_changed_since_start(self):
        self.touch(self.py, 100); self.touch(self.html, 100)
        self.assertEqual(dashboard.changed_since(200, self.root), [])

    def test_a_newer_file_is_named(self):
        self.touch(self.py, 100); self.touch(self.html, 300)
        self.assertEqual(dashboard.changed_since(200, self.root), ["leadkit/data/dashboard.html"])

    def test_only_code_counts(self):
        self.touch(self.py, 100); self.touch(self.html, 100)
        (self.root / "leadkit" / "notes.md").write_text("x")
        self.assertEqual(dashboard.changed_since(200, self.root), [])


if __name__ == "__main__":
    unittest.main()
