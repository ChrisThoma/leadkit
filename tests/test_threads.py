"""Threads: marking replies posted in both forms, and the search URLs."""
import contextlib, io, json, shutil, subprocess, sys, unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import product, threads, threadsapi, tsv  # noqa: E402
from leadkit.product import settings  # noqa: E402
from helpers import TempProduct  # noqa: E402


class MarkPostedTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.t.write("Threads", [
            {"url": "https://www.threads.com/@a/post/P1", "reply": "x", "status": "draft"},
            {"url": "https://www.threads.com/@b/post/P2", "reply": "x", "status": "skip"},
            {"url": "https://www.threads.com/@c/post/P3", "reply": "x", "status": "new"},
        ])

    def tearDown(self):
        self.t.close()

    def test_pairs_from_the_replies_page_record_the_reply(self):
        threads.mark_posted(self.t.p, ["/@a/post/P1 /@mythreadshandle/post/R1", "/@b/post/P2 /@mythreadshandle/post/R2"])
        a, b, c = self.t.read("Threads")
        self.assertEqual(a["status"], "posted")
        self.assertIn("Reply: https://www.threads.com/@mythreadshandle/post/R1", a["notes"])
        self.assertEqual(b["status"], "posted")  # skipped, then answered anyway
        self.assertEqual(c["status"], "new")

    def test_a_reply_naming_another_app_leaves_the_row_open(self):
        # Two apps can draft for the same showcase thread. Matching only the
        # parent thread would mark this app's draft posted by the other app's reply.
        threads.mark_posted(self.t.p, [
            "/@a/post/P1 /@mythreadshandle/post/R1 Mossling, a tiny moss terrarium for your Home Screen. https://l.threads.com/?u=id1000000003",
            "/@b/post/P2 /@mythreadshandle/post/R2 Cragbook, a logbook for your climbs.",
        ])
        a, b, c = self.t.read("Threads")
        self.assertEqual(a["status"], "draft")
        self.assertNotIn("R1", a["notes"])
        self.assertEqual(b["status"], "skip")

    def test_a_reply_naming_this_app_marks_it(self):
        store_id = self.t.p.need("APP_STORE_ID")
        threads.mark_posted(self.t.p, [
            f"/@a/post/P1 /@mythreadshandle/post/R1 I made {self.t.p.title.lower()} for this.",
            f"/@b/post/P2 /@mythreadshandle/post/R2 Try it: https://l.threads.com/?u=https%3A%2F%2Fapps.apple.com%2Fapp%2Fid{store_id}%3Fct%3Dthreads",
        ])
        a, b, c = self.t.read("Threads")
        self.assertEqual(a["status"], "posted")  # the name, any case
        self.assertEqual(b["status"], "posted")  # or the store link alone

    def test_replies_reader_emits_text_and_links(self):
        js = threads.replies_js()
        self.assertIn("innerText", js)
        self.assertIn("href", js)

    def test_a_row_already_replied_gets_the_reply_note_and_keeps_its_status(self):
        self.t.write("Threads", [
            {"url": "https://www.threads.com/@a/post/P1", "status": "replied", "notes": "from the drafts page"},
            {"url": "https://www.threads.com/@b/post/P2", "status": "posted"},
            {"url": "https://www.threads.com/@c/post/P3", "status": "posted", "notes": "Reply: https://www.threads.com/@mythreadshandle/post/OLD x"},
        ])
        changed = threads.mark_posted(self.t.p, ["/@a/post/P1 /@mythreadshandle/post/R1", "/@b/post/P2 /@mythreadshandle/post/R2",
                                                 "/@c/post/P3 /@mythreadshandle/post/R3"])
        a, b, c = self.t.read("Threads")
        self.assertEqual((a["status"], b["status"], c["status"]), ("replied", "posted", "posted"))
        self.assertEqual(a["notes"], "Reply: https://www.threads.com/@mythreadshandle/post/R1 from the drafts page")
        self.assertEqual(b["notes"], "Reply: https://www.threads.com/@mythreadshandle/post/R2")
        self.assertNotIn("R3", c["notes"])  # already has a reply note
        self.assertEqual(len(changed), 2)

    def test_the_product_check_still_applies_to_a_posted_row(self):
        self.t.write("Threads", [{"url": "https://www.threads.com/@a/post/P1", "status": "replied"}])
        threads.mark_posted(self.t.p, ["/@a/post/P1 /@mythreadshandle/post/R1 Mossling, a tiny moss terrarium for your Home Screen."])
        self.assertEqual(self.t.read("Threads")[0]["notes"], "")

    def test_a_plain_url_marks_an_open_row(self):
        threads.mark_posted(self.t.p, ["https://www.threads.com/@c/post/P3?xmt=1", "https://www.threads.com/@b/post/P2"])
        a, b, c = self.t.read("Threads")
        self.assertEqual(c["status"], "posted")
        self.assertEqual(b["status"], "skip")  # a bare URL doesn't revive a skip

    def test_a_reply_without_text_on_a_thread_another_app_logged_is_left_alone(self):
        """Both apps logged the thread and the pair came without its text, so it can't
        tell whose reply it is."""
        other = TempProduct("mossling")
        self.addCleanup(other.close)
        other.write("Threads", [{"url": "https://www.threads.com/@a/post/P1", "reply": "x", "status": "draft"}])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            threads.mark_posted(self.t.p, ["/@a/post/P1 /@mythreadshandle/post/R1", "https://www.threads.com/@a/post/P1",
                                           "/@c/post/P3 /@mythreadshandle/post/R3"], others=[other.p])
        a, b, c = self.t.read("Threads")
        self.assertEqual(a["status"], "draft")
        self.assertEqual(c["status"], "posted")  # a thread only this app logged still counts
        self.assertIn("Mossling also logged", err.getvalue())

    def test_text_that_names_the_app_still_counts_on_a_shared_thread(self):
        other = TempProduct("mossling")
        self.addCleanup(other.close)
        other.write("Threads", [{"url": "https://www.threads.com/@a/post/P1", "status": "draft"}])
        threads.mark_posted(self.t.p, ["/@a/post/P1 /@mythreadshandle/post/R1 Knitwit counts my rows"],
                            others=[other.p])
        self.assertEqual(self.t.read("Threads")[0]["status"], "posted")


class QueryOfTest(unittest.TestCase):
    def test_the_column_wins_over_the_notes(self):
        self.assertEqual(threads.query_of({"query": "Drop Your App", "notes": 'Search "other": x'}), "drop your app")

    def test_older_notes_in_each_form(self):
        cases = [
            ('Search "What are you building": thread about apps', "what are you building"),
            ("Found by 'drop your app'. Posted.", "drop your app"),
            ("Found by Top search \u201crow counter tips\u201d. Reads well", "row counter tips"),
            ('Found by Top search "learning to knit".', "learning to knit"),
            ('"Yarn Love" tag Recent: someone asking', "yarn love"),
            ("\u201cYarn Love\u201d TAG recent: someone", "yarn love"),
            ("From the Climbing Threads community. Good fit", "climbingthreads"),
            ("Bouldering Threads feed, nothing else", "boulderingthreads"),
            ("Knitting Threads, first page", "knittingthreads"),
            ("Seen in Tech Threads", "techthreads"),
            ("AI Threads and Craft Threads", "aithreads"),
            ("Business Threads", "businessthreads"),
        ]
        for notes, want in cases:
            self.assertEqual(threads.query_of({"notes": notes}), want, notes)

    def test_one_spelling_for_the_same_search(self):
        for q in ("Climbing Threads", "climbingthreads", "tag:Climbing Threads", " TAG:climbing threads "):
            self.assertEqual(threads.query_of({"query": q}), "climbingthreads", q)
        self.assertEqual(threads.query_of({"query": "tag:bouldering"}), "bouldering")
        self.assertEqual(threads.query_of({"query": "bouldering"}), "bouldering")

    def test_search_forms_beat_a_community_name(self):
        self.assertEqual(threads.query_of({"notes": 'Climbing Threads. Search "learn to lead": x'}), "learn to lead")

    def test_threads_alone_is_not_a_community(self):
        for notes in ("posted on Threads", "Replied to Threads user", "Meta Threads API", "Top Threads",
                      "Search Threads", "Recent Threads", "Posted to Threads"):
            self.assertEqual(threads.query_of({"notes": notes}), "", notes)

    def test_nothing_recorded(self):
        for row in ({}, {"notes": "found by hand", "query": " "}, {"notes": None}):
            self.assertEqual(threads.query_of(row), "")


class ExtractHeaderTest(unittest.TestCase):
    """EXTRACT_JS runs in a Chrome tab; node stands in with a page that has no posts."""

    def run_js(self, search):
        script = ("globalThis.location={search:%s};globalThis.document={querySelectorAll:()=>[]};"
                  "console.log(JSON.stringify(%s))" % (json.dumps(search), threads.EXTRACT_JS))
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    @unittest.skipUnless(shutil.which("node"), "node is needed to run the extractor")
    def test_header_names_the_query_and_tab(self):
        self.assertEqual(self.run_js("?q=drop%20your%20app"), "# search: drop your app (top)")
        self.assertEqual(self.run_js("?q=Yarn%20Love&serp_type=tags&filter=recent"),
                         "# search: Yarn Love (recent, tag)")
        self.assertEqual(self.run_js("?q=a&tag_id=9&filter=recent&serp_type=tags").split(" (")[1], "recent, tag)")

    @unittest.skipUnless(shutil.which("node"), "node is needed to run the extractor")
    def test_no_header_off_a_search_page(self):
        self.assertEqual(self.run_js(""), "")
        self.assertEqual(self.run_js("?filter=recent"), "")


class ApiWatchQueryTest(unittest.TestCase):
    """api_watch's network layer is urllib, so the seam here is api_search plus
    the token and mentions lookups."""

    def setUp(self):
        self.t = TempProduct()
        self.p = self.t.p
        self.p.cfg.THREADS_KEYWORDS = ["row counter"]
        self.p.cfg.THREADS_TAGS = ["knitting"]
        self.p.cfg.THREADS_MIN_SCORE = 0

    def tearDown(self):
        self.t.close()

    def watch(self):
        def search(q, mode, since, tok, pause):
            return [{"id": f"{mode}-1", "username": "someone", "text": "row counter help",
                     "permalink": f"https://www.threads.com/@someone/post/{mode}"}]
        with mock.patch.object(threads, "token", return_value="tok"), \
             mock.patch.object(threads, "api_search", side_effect=search), \
             mock.patch.object(threads, "add_mentions", return_value=[]), \
             mock.patch.object(threads, "api_score", return_value=(5, [])), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return threads.api_watch(self.p, pause=0)

    def test_rows_say_which_search_found_them(self):
        self.watch()
        got = {r["id"]: r["query"] for r in self.t.read("Threads")}
        self.assertEqual(got, {"KEYWORD-1": "row counter", "TAG-1": "tag:knitting"})

    def test_an_older_file_gets_the_column(self):
        old = [f for f in threads.FIELDS if f != "query"]
        self.t.write("Threads", [{"url": "https://www.threads.com/@x/post/OLD", "reply": "a\n\nb", "status": "new"}], fields=old)
        self.watch()
        fields, rows = tsv.read(self.p.threads_tsv)
        self.assertIn("query", fields)
        self.assertEqual(rows[0]["reply"], "a\n\nb")
        self.assertEqual(rows[0]["query"], "")
        self.assertEqual(sorted(r["query"] for r in rows[1:]), ["row counter", "tag:knitting"])


class SearchTest(unittest.TestCase):
    def test_tag_and_recent_urls(self):
        self.assertEqual(threads.search_url("Yarn Love", threads.RECENT, True),
                         "https://www.threads.com/search?q=Yarn%20Love&serp_type=tags&filter=recent")

    def test_every_product_has_searches(self):
        for p in product.everything():
            with self.subTest(product=p.name):
                self.assertTrue(p.cfg.THREADS_SEARCHES)

    def test_replies_reader_names_the_account(self):
        self.assertIn(f"/@{settings.THREADS_ACCOUNT}/", threads.replies_js())
        self.assertNotIn("'ME'", threads.replies_js())


class LoginTest(unittest.TestCase):
    def test_authorize_url_asks_for_every_scope(self):
        url = threads.authorize_url()
        self.assertTrue(url.startswith("https://threads.net/oauth/authorize?"))
        self.assertIn(f"client_id={settings.THREADS_APP_ID}", url)
        # The token generator never grants these three; only this page does.
        for scope in ("threads_keyword_search", "threads_manage_mentions", "threads_delete"):
            self.assertIn(scope, url)

    def test_code_comes_out_of_the_pasted_redirect(self):
        # Threads appends "#_" to the redirect; it isn't part of the code.
        self.assertEqual(threads.login_code("https://example.com/?code=AQBx12#_"), "AQBx12")
        self.assertEqual(threads.login_code("AQBx12#_"), "AQBx12")
