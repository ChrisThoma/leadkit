import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import mlog  # noqa: E402

APPS = ["Knitwit", "Tally Jar", "Cragbook", "Paper Kite", "Mossling"]

ASC = """date\ttitle\tkind\tunits\tproceeds\tcountries\tredownloads\tproceeds_by_currency\tsales
2026-11-13\tMossling: Tiny Terrarium\tapp\t12\t10.00\tBE,US\t0\t\t12.00
2026-11-13\tQuillbox Writing Prompts\tapp\t3\t0.00\tUS\t0\t\t0.00
2026-11-07\tKnitwit: Row Counter\t\t0\t0.00\t\t1\t\t0.00
"""
PLAY = """date\ttitle\tkind\tunits\tcharged\tcountries\tproceeds\tsales
2026-11-11\tKnitwit: contador de vueltas\tapp\t1\t4.99 BRL\tBR\t0.70\t0.80
2026-11-11\tKnitwit: Row Counter\tapp\t2\t2.00 USD\tUS\t1.60\t2.00
"""


class SalesTest(unittest.TestCase):
    """Units for several apps come from two stores and several metrics files, and
    one log has to show a week at a glance."""

    def test_localized_titles_map_to_one_app(self):
        self.assertEqual(mlog.app_of("Knitwit: contador de vueltas", APPS), "Knitwit")
        self.assertEqual(mlog.app_of("Tally Jar: Habit Counter", APPS), "Tally Jar")

    def test_apps_outside_leadkit_keep_their_title(self):
        self.assertEqual(mlog.app_of("Quillbox Writing Prompts", APPS), "Quillbox Writing Prompts")

    def test_asc_rows(self):
        rows = mlog.parse_sales(ASC, "iOS", APPS)
        self.assertIn({"date": "2026-11-13", "app": "Mossling", "store": "iOS", "units": "12",
                       "proceeds": "10.00", "sales": "12.00"}, rows)
        self.assertEqual(len(rows), 2, "a redownload-only row with 0 units is not a sale")

    def test_play_rows_for_one_app_on_one_day_add_up(self):
        rows = mlog.parse_sales(PLAY, "Play", APPS)
        self.assertEqual(rows, [{"date": "2026-11-11", "app": "Knitwit", "store": "Play", "units": "3",
                                 "proceeds": "2.30", "sales": "2.80"}], "dollars add up across currencies too")

    def test_a_new_pull_replaces_the_same_day(self):
        old = [{"date": "2026-11-13", "app": "Mossling", "store": "iOS", "units": "10"},
               {"date": "2026-11-01", "app": "Mossling", "store": "iOS", "units": "1"}]
        new = [{"date": "2026-11-13", "app": "Mossling", "store": "iOS", "units": "12"}]
        merged = mlog.merge_sales(old, new, start="2026-11-10")
        self.assertEqual(sorted((r["date"], r["units"]) for r in merged),
                         [("2026-11-01", "1"), ("2026-11-13", "12")])

    def test_a_day_that_vanished_from_the_pull_is_dropped(self):
        old = [{"date": "2026-11-13", "app": "Mossling", "store": "iOS", "units": "10"}]
        self.assertEqual(mlog.merge_sales(old, [], start="2026-11-10"), [])


class PostsTest(unittest.TestCase):
    def test_threads_post_app_from_text(self):
        self.assertEqual(mlog.app_in("New in Mossling: ferns", APPS), "Mossling")
        self.assertEqual(mlog.app_in("Wound three skeins today and cast on a hat", APPS), "")

    def test_latest_insights_row_wins(self):
        rows = [
            {"date": "2026-11-16", "posted": "2026-11-16 09:00", "url": "u1", "text": "New in Mossling: ferns",
             "views": "4", "likes": "1", "replies": "2"},
            {"date": "2026-11-17", "posted": "2026-11-16 09:00", "url": "u1", "text": "New in Mossling: ferns",
             "views": "8", "likes": "1", "replies": "2"},
        ]
        out = mlog.threads_posts(rows, APPS)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["date"], out[0]["app"], out[0]["channel"], out[0]["views"]),
                         ("2026-11-16", "Mossling", "Threads", "8"))

    def test_experiment_rows(self):
        rows = [{"id": "E12", "publish_date": "2026-10-26 (YouTube and Reel posted)",
                 "channel": "YouTube Shorts, Instagram Reels", "post_url": "https://youtu.be/x",
                 "result": "Result: 100 views, 50 engaged"},
                {"id": "E9", "publish_date": "", "channel": "Threads", "post_url": "", "result": ""}]
        out = mlog.experiment_posts("Knitwit", rows)
        self.assertEqual(len(out), 1, "a planned experiment that never ran isn't a post")
        self.assertEqual((out[0]["date"], out[0]["ref"], out[0]["url"]), ("2026-10-26", "E12", "https://youtu.be/x"))

    def test_one_row_per_link_with_the_channel_from_the_link(self):
        rows = [{"id": "E2", "publish_date": "2026-10-28", "channel": "YouTube Shorts, Instagram Reels, Threads",
                 "post_url": "https://youtube.com/shorts/AbCdEfGhIjK; https://www.instagram.com/reel/abc/; "
                             "https://www.threads.com/@mythreadshandle/post/DxExAmPLe01?xmt=1",
                 "result": ""}]
        out = mlog.experiment_posts("Knitwit", rows)
        self.assertEqual([(r["channel"], r["url"]) for r in out], [
            ("YouTube", "https://youtube.com/shorts/AbCdEfGhIjK"),
            ("Instagram", "https://www.instagram.com/reel/abc/"),
            ("Threads", "https://www.threads.com/@mythreadshandle/post/DxExAmPLe01"),
        ])

    def test_words_in_the_link_column_are_not_a_link(self):
        rows = [{"id": "E7", "publish_date": "2026-11-09", "channel": "Threads video (Instagram to follow)",
                 "post_url": "(link not recorded)", "result": ""}]
        (r,) = mlog.experiment_posts("Cragbook", rows)
        self.assertEqual((r["url"], r["channel"]), ("", "Threads video"))

    def test_reddit_channel_names_the_sub(self):
        rows = [{"id": "E4", "publish_date": "2026-11-13", "channel": "Reddit r/ipadapps (Showcase flair)",
                 "post_url": "https://www.reddit.com/r/ipadapps/comments/abc123/", "result": ""}]
        self.assertEqual(mlog.experiment_posts("Mossling", rows)[0]["channel"], "Reddit r/ipadapps")

    def test_numbers_read_from_youtube_and_reddit(self):
        posts = [dict.fromkeys(mlog.POST_FIELDS, "") | {"url": "https://youtube.com/shorts/a", "channel": "YouTube"},
                 dict.fromkeys(mlog.POST_FIELDS, "") | {"url": "https://www.reddit.com/r/x/comments/b/", "channel": "Reddit r/x"},
                 dict.fromkeys(mlog.POST_FIELDS, "") | {"url": "https://www.threads.com/@a/post/c", "channel": "Threads"}]
        got = mlog.read_numbers(posts, youtube=lambda u: ("405", "2", "1"), reddit=lambda u: ("3", "", "4"))
        self.assertEqual([(r["views"], r["likes"], r["replies"]) for r in got],
                         [("405", "2", "1"), ("", "3", "4")])

    def test_merge_posts_keeps_numbers_set_by_hand(self):
        old = [{"date": "2026-10-26", "app": "Knitwit", "channel": "YouTube Shorts", "ref": "E12",
                "url": "https://youtu.be/x", "views": "100", "likes": "5", "replies": "", "result": "", "source": "set"}]
        new = [{"date": "2026-10-26", "app": "Knitwit", "channel": "YouTube Shorts", "ref": "E12",
                "url": "https://youtu.be/x", "views": "", "likes": "", "replies": "", "result": "Pending",
                "source": "experiments"}]
        merged = mlog.merge_posts(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["views"], "100")


class OwnRedditTest(unittest.TestCase):
    """Sync copies each app's own Reddit posts into posts.tsv, so a search there finds them."""

    ROW = {"posted": "2026-11-20", "sub": "terrariums", "title": "I made a tiny terrarium",
           "url": "https://www.reddit.com/r/terrariums/comments/abc123/", "score": "4", "comments": "0"}

    def test_own_posts_become_rows(self):
        (r,) = mlog.own_reddit_posts("Mossling", [self.ROW])
        self.assertEqual((r["date"], r["app"], r["channel"], r["likes"], r["replies"], r["note"]),
                         ("2026-11-20", "Mossling", "Reddit r/terrariums", "4", "0", "I made a tiny terrarium"))

    def test_a_link_with_a_slug_is_the_same_post(self):
        old = mlog._blank(date="2026-11-20", app="Mossling", channel="Reddit r/terrariums", ref="E9",
                          url=self.ROW["url"] + "i_made_a_tiny_terrarium/", result="kept")
        merged = mlog.merge_posts([old], mlog.own_reddit_posts("Mossling", [self.ROW]))
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["ref"], merged[0]["url"], merged[0]["likes"]), ("E9", old["url"], "4"))

    def test_refresh_logs_each_products_posts_and_survives_a_failed_fetch(self):
        from leadkit import posts
        from unittest import mock
        with mock.patch.object(posts, "fetch_own", side_effect=OSError("down")), \
             mock.patch.object(posts, "log") as log:
            self.assertIn("kept the old rows", mlog.refresh_own_reddit())
            log.assert_not_called()
        with mock.patch.object(posts, "fetch_own", return_value=[]), mock.patch.object(posts, "log") as log:
            self.assertEqual(mlog.refresh_own_reddit(), "")
            self.assertTrue(log.called)


class UnreadTest(unittest.TestCase):
    """A post whose result still says "Pending" a week on has never been read."""

    def row(self, **kw):
        return dict.fromkeys(mlog.POST_FIELDS, "") | {"date": "2026-11-10"} | kw

    def test_no_numbers_is_unread(self):
        self.assertTrue(mlog.unread(self.row(result="Uploaded with no issues."), "2026-11-17"))

    def test_views_or_result_numbers_count_as_read(self):
        self.assertFalse(mlog.unread(self.row(views="340"), "2026-11-17"))
        self.assertFalse(mlog.unread(self.row(result="3 upvotes, 2 comments"), "2026-11-17"))

    def test_too_new_to_read(self):
        self.assertFalse(mlog.unread(self.row(date="2026-11-16"), "2026-11-17"))


class WeekTest(unittest.TestCase):
    def test_week_report_lists_units_posts_and_unread(self):
        sales = [{"date": "2026-11-13", "app": "Mossling", "store": "iOS", "units": "12"},
                 {"date": "2026-11-14", "app": "Mossling", "store": "Play", "units": "1"},
                 {"date": "2026-11-05", "app": "Mossling", "store": "iOS", "units": "2"}]
        posts = [dict.fromkeys(mlog.POST_FIELDS, "") | {"date": "2026-11-13", "app": "Mossling",
                 "channel": "Threads", "url": "u1", "views": "155"},
                 dict.fromkeys(mlog.POST_FIELDS, "") | {"date": "2026-11-12", "app": "Mossling",
                 "channel": "YouTube Shorts", "url": "u2", "ref": "E1"}]
        out = mlog.week_report(sales, posts, "2026-11-10", "2026-11-16", today="2026-11-17")
        self.assertIn("Mossling", out)
        line = next(l for l in out.splitlines() if l.startswith("| Mossling"))
        self.assertIn("| 13 |", line, "iOS and Play together this week")
        self.assertIn("| 2 |", line, "last week's units beside it")
        self.assertIn("u2", out, "an unread post is listed so it gets read")

    def test_an_unread_reel_is_listed_with_its_insights_page(self):
        posts = [dict.fromkeys(mlog.POST_FIELDS, "") | {"date": "2026-11-12", "app": "Knitwit",
                 "channel": "Instagram", "url": "https://www.instagram.com/reel/Dk3xAmPLe1Q/"}]
        out = mlog.week_report([], posts, "2026-11-10", "2026-11-16", today="2026-11-17")
        self.assertIn("https://www.instagram.com/insights/media/4122979529216879952/", out)


def post(**kw):
    return dict.fromkeys(mlog.POST_FIELDS, "") | kw


class DayTest(unittest.TestCase):
    """`leads log day`: one day's sales and posts for the daily recap."""
    SALES = [
        {"date": "2026-11-22", "app": "Mossling", "store": "iOS", "units": "2", "proceeds": "2.00", "sales": "2.50"},
        {"date": "2026-11-22", "app": "Mossling", "store": "Play", "units": "1", "proceeds": "0.80", "sales": "1.00"},
        {"date": "2026-11-20", "app": "Cragbook", "store": "iOS", "units": "4", "proceeds": "8.00", "sales": "10.00"},
        {"date": "2026-11-12", "app": "Cragbook", "store": "iOS", "units": "1", "proceeds": "1.00", "sales": "1.40"},
        {"date": "2026-11-21", "app": "Knitwit", "store": "Play", "units": "1", "proceeds": "1.50", "sales": "2.00"},
    ]
    POSTS = [
        post(date="2026-11-22", app="Knitwit", channel="YouTube", ref="E3", url="yt", views="200", likes="10"),
        post(date="2026-11-22", app="Mossling", channel="Threads", ref="E2", url="th", views="50"),
        post(date="2026-11-19", app="Knitwit", channel="Instagram", ref="E1", url="ig", views="100"),
        post(date="2026-11-10", app="Knitwit", channel="Threads", url="old", views="900"),
    ]

    def day(self):
        return mlog.day_report(self.SALES, self.POSTS, "2026-11-22", today="2026-11-23")

    def test_the_days_sales_by_app_with_stores_added(self):
        d = self.day()
        self.assertEqual(d["day"]["Mossling"], {"units": 3, "proceeds": 2.8, "sales": 3.5})
        self.assertEqual(d["day_total"]["units"], 3)

    def test_seven_days_against_the_seven_before(self):
        d = self.day()
        self.assertEqual(d["week"]["Cragbook"], {"units": 4, "proceeds": 8.0, "units_before": 1, "proceeds_before": 1.0})
        self.assertEqual(d["week_total"]["units"], 8)
        self.assertEqual(d["week_total"]["units_before"], 1)

    def test_the_newest_sales_date_per_store_shows_a_day_not_in_yet(self):
        d = self.day()
        self.assertEqual(d["sales_through"], {"iOS": "2026-11-22", "Play": "2026-11-22"})

    def test_the_days_posts_and_the_weeks_best(self):
        d = self.day()
        self.assertEqual([p["ref"] for p in d["posts"]], ["E3", "E2"])
        self.assertEqual([p["url"] for p in d["top_posts"]], ["yt", "ig", "th"], "the last 7 days, most views first")

    def test_unread_count(self):
        self.assertEqual(mlog.day_report([], [post(date="2026-11-15", app="X", channel="Threads", url="u")],
                                         "2026-11-22", today="2026-11-23")["unread"], 1)


class RetentionTest(unittest.TestCase):
    """Views alone don't say how much of a video was watched: the log keeps retention
    too, and points at each Reel's insights page so its numbers get read."""

    def row(self, **kw):
        return dict.fromkeys(mlog.POST_FIELDS, "") | {"date": "2026-10-29", "channel": "YouTube",
                                                      "url": "https://youtube.com/shorts/a"} | kw

    def test_stayed_and_watched_survive_a_sync(self):
        self.assertLessEqual({"stayed", "watched"}, set(mlog.POST_FIELDS), "or the file drops them")
        merged = mlog.merge_posts([self.row(stayed="39.3", watched="48.5", views="1352")],
                                  [self.row(views="1400")])
        self.assertEqual((merged[0]["stayed"], merged[0]["watched"], merged[0]["views"]),
                         ("39.3", "48.5", "1400"))

    def test_a_reels_insights_page_comes_from_its_shortcode(self):
        want = "https://www.instagram.com/insights/media/4122979529216879952/"
        self.assertEqual(mlog.insights_url("https://www.instagram.com/reel/Dk3xAmPLe1Q/"), want)
        self.assertEqual(mlog.insights_url("https://www.instagram.com/mythreadshandle/reel/Dk3xAmPLe1Q/"), want)
        self.assertEqual(mlog.insights_url("https://youtube.com/shorts/a"), "")


if __name__ == "__main__":
    unittest.main()


class ToolPathTest(unittest.TestCase):
    """The dashboard's Sync button may run without the sales tools on PATH."""

    def test_finds_sales_tools_off_path(self):
        import os, tempfile
        from unittest import mock
        from leadkit import product
        with tempfile.TemporaryDirectory() as home:
            local = Path(home) / ".local/bin"
            local.mkdir(parents=True)
            (local / "other-tool").write_text("#!/bin/sh\n")
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}), \
                 mock.patch.object(Path, "home", return_value=Path(home)):
                self.assertEqual(mlog.tool("asc-sales"), str(product.HOME / "bin" / "asc-sales"))
                self.assertEqual(mlog.tool("other-tool"), str(local / "other-tool"))
                self.assertEqual(mlog.tool("no-such-tool"), "no-such-tool")
