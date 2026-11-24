"""X: cross-posting a Threads post, the leads searches, X rows on the drafts page
and in `leads set`, marking posted, and the daily insights log."""
import sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import drafts, rows, threads, tsv, x  # noqa: E402
from helpers import TempProduct, ago  # noqa: E402

APP = "https://apps.apple.com/app/apple-store/id1000000001?pt=123456&ct=threads_idea&mt=8"
PLAY = ("https://play.google.com/store/apps/details?id=com.example.mossling"
        "&referrer=utm_source%3Dthreads%26utm_campaign%3Dandroidad")

TIP_POST = ("Here's a tip from Knitwit, the app I made because I kept losing count of my rows halfway "
            "through a pattern:\n\nBefore you start a cable section, set a second counter for the repeat, so "
            "the rows and the cable crossings each keep their own place. Put the work down mid-row, pick it up "
            "a week later, and both counts are where you left them.\n\nIt counts rows, rounds and repeats "
            "for knitting and crochet, one counter per pattern piece. Link in the reply.")
TIP_REPLY = f"$2.99 once on iPhone, with no ads, no account and no subscription.\n{APP}"


class LengthTest(unittest.TestCase):
    def test_a_link_counts_23_whatever_its_length(self):
        self.assertEqual(x.length(f"Get it: {APP}"), len("Get it: ") + 23)
        self.assertEqual(x.length("plain"), 5)


class CampaignTest(unittest.TestCase):
    def test_threads_codes_become_x_codes(self):
        self.assertIn("ct=x_idea&", x.campaign(APP))
        self.assertIn("utm_source%3Dx%26", x.campaign(PLAY))
        self.assertIn("ct=x&", x.campaign("https://apps.apple.com/app/id1?ct=threads&mt=8"))


class CrossPostTest(unittest.TestCase):
    def test_a_short_post_keeps_its_link_reply(self):
        post = "Mossling is on Android now. Link in the reply."
        self.assertEqual(x.crosspost(post, f"It's $0.99.\n{PLAY}"),
                         [post, f"It's $0.99.\n{x.campaign(PLAY)}"])

    def test_a_long_post_splits_at_paragraphs_and_the_link_joins_the_last(self):
        # Splitting at paragraphs keeps the post as written, rather than trimming it to fit.
        parts = x.crosspost(TIP_POST, TIP_REPLY)
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[0].endswith("halfway through a pattern:"))
        self.assertTrue(parts[1].startswith("Before you start a cable section"))
        self.assertEqual(parts[2], "It counts rows, rounds and repeats for knitting and crochet, one counter "
                                   "per pattern piece. $2.99 once on iPhone, with no ads, no account and no subscription.\n"
                                   + x.campaign(APP))
        self.assertTrue(all(x.length(p) <= x.LIMIT for p in parts))

    def test_a_reply_that_wont_fit_stays_its_own_post(self):
        long_reply = "word " * 50 + APP
        parts = x.crosspost(TIP_POST, long_reply)
        self.assertTrue(parts[-2].endswith("Link in the reply."))
        self.assertTrue(parts[-1].startswith("word"))

    def test_a_paragraph_over_the_limit_splits_at_sentences(self):
        para = " ".join(f"Sentence number {i} is here." for i in range(20))
        parts = x.crosspost(para, "")
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(x.length(p) <= x.LIMIT for p in parts))
        self.assertEqual(" ".join(parts), para)


class SearchTest(unittest.TestCase):
    def test_threads_searches_carry_over_with_recent_as_latest(self):
        t = TempProduct("mossling")
        groups = x.groups(t.p)
        self.assertIn("keywords", groups)
        urls = [x.search_url(*s) for s in groups["keywords"]]
        self.assertIn("https://x.com/search?q=mossling&src=typed_query&f=live", urls)
        self.assertIn("https://x.com/search?q=terrarium%20app&src=typed_query", urls)
        t.close()

    def test_a_product_can_list_its_own_x_searches(self):
        t = TempProduct("mossling")
        t.p.cfg.X_SEARCHES = {"only": [("moss", x.LATEST)]}
        self.assertEqual(list(x.groups(t.p))[0], "only")
        t.close()


class RowsTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()

    def tearDown(self):
        self.t.close()

    def test_set_adds_an_x_row_to_the_x_file(self):
        url = "https://x.com/someone/status/123?s=20"
        self.assertEqual(rows.platform(url), "X")
        self.assertEqual(rows.platform("https://twitter.com/someone/status/123"), "X")
        rows.set_row(self.t.p, url, {"kind": "domain", "author": "someone", "reply": "hi"}, add=True)
        got = tsv.read(self.t.p.x_tsv)[1]
        self.assertEqual([r["author"] for r in got], ["someone"])

    def test_drafts_page_shows_x_rows_and_counts_x_length(self):
        tsv.write(self.t.p.x_tsv, threads.FIELDS, [
            dict.fromkeys(threads.FIELDS, "") | {"url": "https://x.com/a/status/1", "author": "a",
                                                 "found": ago(0), "reply": "short " + APP},
            dict.fromkeys(threads.FIELDS, "") | {"url": "https://x.com/b/status/2", "author": "b",
                                                 "found": ago(0), "reply": "y" * 281}])
        got = {r["author"]: r for r in drafts.load([self.t.p])}
        self.assertEqual(got["a"]["platform"], "X")
        self.assertEqual(got["a"]["warnings"], [])
        self.assertIn("over X's 280", got["b"]["warnings"][0])

    def test_mark_posted(self):
        tsv.write(self.t.p.x_tsv, threads.FIELDS, [
            dict.fromkeys(threads.FIELDS, "") | {"url": "https://x.com/a/status/1", "reply": "hi", "status": "draft"}])
        x.mark_posted(self.t.p, ["https://x.com/a/status/1 https://x.com/my_x_handle/status/9"])
        r = tsv.read(self.t.p.x_tsv)[1][0]
        self.assertEqual(r["status"], "posted")
        self.assertIn("https://x.com/my_x_handle/status/9", r["notes"])


class InsightsTest(unittest.TestCase):
    def test_logs_each_post_once_a_day(self):
        t = TempProduct()
        path = t.tmp / "x-insights.tsv"
        answers = {
            "users/by/username/my_x_handle": {"data": {"id": "42"}},
            "users/42/tweets": {"data": [{"id": "7", "text": "Mossling is on Android now.\nLink",
                                          "created_at": "2026-11-16T22:01:00.000Z",
                                          "public_metrics": {"impression_count": 12, "like_count": 1,
                                                             "reply_count": 0, "retweet_count": 0,
                                                             "quote_count": 0, "bookmark_count": 2}}]},
        }
        calls = []

        def fake(path_, tok, params=None):
            calls.append((path_, params))
            return answers[path_]
        with mock.patch.object(x, "call", fake):
            x.log_insights("tok", path)
            x.log_insights("tok", path)
        got = tsv.read(path)[1]
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["posted"], got[0]["views"], got[0]["bookmarks"]), ("2026-11-16 22:01", "12", "2"))
        self.assertEqual(got[0]["url"], "https://x.com/my_x_handle/status/7")
        self.assertEqual(calls[1][1]["exclude"], "replies,retweets")
        t.close()

    def test_no_token_says_how_to_get_one(self):
        with mock.patch.object(x, "TOKEN_FILE", Path("/nonexistent/x_bearer_token")), \
             mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as e:
                x.token()
        self.assertIn("console.x.com", str(e.exception))

    def test_plist_runs_the_scheduled_log(self):
        import plistlib
        job = plistlib.loads(x.insights_plist(9, 25, Path("/repo"), "/py", Path("/log")))
        self.assertEqual(job["ProgramArguments"], ["/py", "-m", "leadkit.cli", "x-insights", "--scheduled"])
        self.assertEqual(job["Label"], x.INSIGHTS_LABEL)


if __name__ == "__main__":
    unittest.main()
