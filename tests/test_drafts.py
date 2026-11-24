"""The drafts page: what it shows, Skip and Undo, clearing old drafts, and a
reload not counting as the tab closing."""
from unittest import mock
import json, sys, threading, time, unittest, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import drafts, product  # noqa: E402
from helpers import TempProduct, ago  # noqa: E402


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()

    def tearDown(self):
        self.t.close()

    def test_only_open_rows_with_a_reply_best_priority_first(self):
        self.t.write("Reddit", [
            {"url": "https://r/1", "reply": '"Quoted reply"', "status": "draft", "priority": "2", "found": ago(0)},
            {"url": "https://r/2", "reply": "Posted one", "status": "posted", "found": ago(0)},
            {"url": "https://r/3", "reply": "", "status": "new", "found": ago(0)},
            {"url": "https://r/4", "reply": "Top", "status": "new", "priority": "1", "found": ago(1)},
        ])
        rows = drafts.load([self.t.p])
        self.assertEqual([r["url"] for r in rows], ["https://r/4", "https://r/1"])
        self.assertEqual(rows[1]["reply_text"], "Quoted reply")

    def test_a_threads_row_shows_the_products_where_column(self):
        t = TempProduct("cragbook")  # THREADS_WHERE = "discipline"
        try:
            from leadkit import threads
            t.write("Threads", [{"url": "https://t/1", "reply": "Hi", "status": "draft", "found": ago(0),
                                 "discipline": "bouldering"}], fields=threads.FIELDS + ["discipline"])
            self.assertEqual(drafts.load([t.p])[0]["where"], "bouldering")
            t.p.cfg.THREADS_WHERE = None
            self.assertEqual(drafts.load([t.p])[0]["where"], "")
        finally:
            t.close()
            product.Product("cragbook")  # reload the config this test changed

    def test_age_is_the_older_of_posted_and_found(self):
        self.assertEqual(drafts.days_old({"posted": ago(5), "found": ago(1)}), 5)
        self.assertEqual(drafts.days_old({"posted": "", "found": ago(2)}), 2)


class ExpireTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()  # Knitwit: STALE_DAYS = 3

    def tearDown(self):
        self.t.close()

    def test_old_drafts_are_skipped_but_own_posts_never(self):
        self.t.write("Reddit", [
            {"url": "https://www.reddit.com/r/a/comments/old/", "reply": "x", "status": "draft", "found": ago(4)},
            {"url": "https://www.reddit.com/r/a/comments/new/", "reply": "x", "status": "draft", "found": ago(3)},
            {"url": "https://www.reddit.com/r/knitting/submit", "reply": "x", "status": "draft", "found": ago(9)},
        ])
        drafts.expire(self.t.p)
        old, new, own = self.t.read("Reddit")
        self.assertEqual(old["status"], "skip")
        self.assertTrue(old["notes"].startswith("Cleared "))
        self.assertEqual(new["status"], "draft")
        self.assertEqual(own["status"], "draft")


class WarningsTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.other = TempProduct("cragbook")

    def tearDown(self):
        self.t.close()
        self.other.close()

    def test_threads_draft_over_the_limit_is_flagged(self):
        self.t.write("Threads", [
            {"url": "https://t/long", "author": "a", "reply": "x" * 501, "status": "draft"},
            {"url": "https://t/fits", "author": "b", "reply": "x" * 500, "status": "draft"},
        ])
        self.t.write("Reddit", [{"url": "https://r/long", "author": "c", "reply": "x" * 900, "status": "draft"}])
        warn = {r["url"]: r["warnings"] for r in drafts.load([self.t.p])}
        self.assertEqual(warn["https://t/long"], ["501 characters, over Threads' 500."])
        self.assertEqual(warn["https://t/fits"], [])
        self.assertEqual(warn["https://r/long"], [])

    def test_author_already_pitched_by_any_product_is_flagged(self):
        # example.handle got a reply on one post; a new post of theirs came back as a lead.
        self.t.write("Threads", [
            {"url": "https://t/old", "author": "example.handle", "reply": "x", "status": "posted"},
            {"url": "https://t/new", "author": "@Example.Handle", "reply": "x", "status": "draft"},
            {"url": "https://t/fresh", "author": "someone", "reply": "x", "status": "draft"},
        ])
        self.other.write("Threads", [{"url": "https://t/f", "author": "someone", "reply": "x", "status": "posted"}])
        warn = {r["url"]: r["warnings"] for r in drafts.load([self.t.p], pitched_from=[self.t.p, self.other.p])}
        self.assertEqual(warn["https://t/new"], ["Already replied to @example.handle before."])
        self.assertEqual(warn["https://t/fresh"], ["Already replied to @someone before."])

    def test_same_name_on_another_platform_is_someone_else(self):
        self.t.write("Reddit", [{"url": "https://r/1", "author": "sam", "reply": "x", "status": "posted"}])
        self.t.write("Threads", [{"url": "https://t/1", "author": "sam", "reply": "x", "status": "draft"}])
        self.assertEqual(drafts.load([self.t.p])[0]["warnings"], [])

    def test_card_shows_the_warning(self):
        self.t.write("Threads", [{"url": "https://t/1", "author": "a", "reply": "x" * 600, "status": "draft"}])
        row = drafts.load([self.t.p])[0]
        self.assertIn('<p class="warn">600 characters', drafts.card(row, ["Knitwit"]))


class SkipTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.t.write("Threads", [{"url": "https://t/1", "reply": "x", "status": "new", "notes": "Hi."}])

    def tearDown(self):
        self.t.close()

    def test_skip_then_undo_restores_status_and_notes(self):
        drafts.set_skipped(self.t.p, "Threads", "https://t/1", True)
        (r,) = self.t.read("Threads")
        self.assertEqual((r["status"], r["notes"]), ("skip", f"Hi. {drafts.SKIP_NOTE}"))
        drafts.set_skipped(self.t.p, "Threads", "https://t/1", False)
        (r,) = self.t.read("Threads")
        self.assertEqual((r["status"], r["notes"]), ("new", "Hi."))

    def test_a_reason_goes_in_the_notes_and_can_change(self):
        drafts.set_skipped(self.t.p, "Threads", "https://t/1", True)
        drafts.set_skip_reason(self.t.p, "Threads", "https://t/1", "Old thread")
        drafts.set_skip_reason(self.t.p, "Threads", "https://t/1", "Weak reply")
        (r,) = self.t.read("Threads")
        self.assertEqual(r["notes"], f"Hi. {drafts.SKIP_NOTE} Reason: Weak reply.")

    def test_undo_takes_the_reason_away_too(self):
        drafts.set_skipped(self.t.p, "Threads", "https://t/1", True)
        drafts.set_skip_reason(self.t.p, "Threads", "https://t/1", "Weak reply")
        drafts.set_skipped(self.t.p, "Threads", "https://t/1", False)
        (r,) = self.t.read("Threads")
        self.assertEqual((r["status"], r["notes"]), ("new", "Hi."))

    def test_a_reason_needs_a_skipped_row(self):
        self.assertEqual(drafts.set_skip_reason(self.t.p, "Threads", "https://t/1", "Weak reply"), [])

    def test_undo_without_a_skip_changes_nothing(self):
        self.assertEqual(drafts.set_skipped(self.t.p, "Threads", "https://t/1", False), [])


class RepliedTest(unittest.TestCase):
    """Already replied: a thread you answered by hand, so the record and the
    already-pitched warning know without waiting for the close sync."""

    def setUp(self):
        self.t = TempProduct()
        self.t.write("Threads", [{"url": "https://t/1", "author": "a", "reply": "x", "status": "draft", "notes": "Hi."}])

    def tearDown(self):
        self.t.close()

    def test_replied_marks_posted_then_undo_restores(self):
        drafts.set_replied(self.t.p, "Threads", "https://t/1", True)
        (r,) = self.t.read("Threads")
        self.assertEqual((r["status"], r["notes"]), ("posted", f"Hi. {drafts.REPLIED_NOTE}"))
        self.assertEqual(drafts.load([self.t.p]), [])
        drafts.set_replied(self.t.p, "Threads", "https://t/1", False)
        (r,) = self.t.read("Threads")
        self.assertEqual((r["status"], r["notes"]), ("draft", "Hi."))

    def test_replied_counts_as_pitched(self):
        drafts.set_replied(self.t.p, "Threads", "https://t/1", True)
        self.assertIn(("Threads", "a"), drafts.pitched([self.t.p]))

    def test_undo_leaves_a_row_posted_elsewhere_alone(self):
        self.t.write("Threads", [{"url": "https://t/1", "reply": "x", "status": "posted"}])
        self.assertEqual(drafts.set_replied(self.t.p, "Threads", "https://t/1", False), [])

    def test_card_has_the_own_reason_box(self):
        row = drafts.load([self.t.p])[0]
        self.assertIn('<form class="own">', drafts.card(row, ["Knitwit"]))

    def test_card_has_the_button(self):
        row = drafts.load([self.t.p])[0]
        self.assertIn('class="replied"', drafts.card(row, ["Knitwit"]))


class ServeTest(unittest.TestCase):
    """The server against a temp product, with sync stubbed so nothing reaches Reddit."""

    def setUp(self):
        self.t = TempProduct()
        self.t.write("Reddit", [{"url": "https://r/1", "reply": "x", "status": "draft", "found": ago(0)}])
        self.synced = []
        self.sync, drafts.sync = drafts.sync, lambda products: self.synced.append(time.time())
        self.grace, drafts.RELOAD_GRACE = drafts.RELOAD_GRACE, 0.3
        self.server = None
        self.thread = threading.Thread(target=self.run_server, daemon=True)
        self.thread.start()
        while not self.server:
            time.sleep(0.01)

    def run_server(self):
        orig = drafts.http.server.ThreadingHTTPServer

        class Capture(orig):
            def __init__(inner, *a, **k):
                super().__init__(*a, **k)
                self.server = inner
        drafts.http.server.ThreadingHTTPServer = Capture
        try:
            drafts.serve([self.t.p], open_browser=False)
        finally:
            drafts.http.server.ThreadingHTTPServer = orig

    def tearDown(self):
        drafts.sync, drafts.RELOAD_GRACE = self.sync, self.grace
        self.t.close()

    def call(self, path, body=None):
        url = f"http://127.0.0.1:{self.server.server_port}{path}"
        data = json.dumps(body).encode() if body is not None else (b"" if path not in ("/", "/state") else None)
        with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
            return r.status, r.read()

    def test_page_lists_the_draft_and_skip_writes_the_tsv(self):
        status, page = self.call("/")
        self.assertIn(b"https://r/1", page)
        self.call("/skip", {"product": "knitwit", "platform": "Reddit", "url": "https://r/1"})
        self.assertEqual(self.t.read("Reddit")[0]["status"], "skip")
        self.call("/closed", {})
        self.thread.join(5)

    def test_the_page_records_a_preset_or_own_reason_and_refuses_empty(self):
        self.call("/skip", {"product": "knitwit", "platform": "Reddit", "url": "https://r/1"})
        lead = {"product": "knitwit", "platform": "Reddit", "url": "https://r/1"}
        self.call("/skip-reason", {**lead, "reason": "Wrong thread"})
        self.assertIn("Reason: Wrong thread.", self.t.read("Reddit")[0]["notes"])
        self.call("/skip-reason", {**lead, "reason": "  OP already\tfound\nan app.  "})
        self.assertTrue(self.t.read("Reddit")[0]["notes"].endswith("Reason: OP already found an app."))
        for bad in ("   ", "x" * (drafts.REASON_LIMIT + 1), 5):
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/skip-reason", {**lead, "reason": bad})
        self.call("/closed", {})
        self.thread.join(5)

    def test_replied_and_unreplied_write_the_tsv(self):
        lead = {"product": "knitwit", "platform": "Reddit", "url": "https://r/1"}
        self.call("/replied", lead)
        self.assertEqual(self.t.read("Reddit")[0]["status"], "posted")
        self.call("/unreplied", lead)
        self.assertEqual(self.t.read("Reddit")[0]["status"], "draft")
        self.call("/closed", {})
        self.thread.join(5)

    def test_a_reload_is_not_a_close(self):
        self.call("/closed", {})
        self.call("/")
        time.sleep(0.6)
        self.assertEqual(self.synced, [])
        self.assertTrue(self.thread.is_alive())
        self.call("/closed", {})
        self.thread.join(5)
        self.assertEqual(len(self.synced), 1)
        self.assertFalse(self.thread.is_alive())

    def state(self):
        return json.loads(self.call("/state")[1])

    def test_state_streams_a_draft_added_after_the_page_loaded(self):
        self.call("/")
        self.t.write("Reddit", [{"url": "https://r/1", "reply": "x", "status": "draft", "found": ago(0)},
                                {"url": "https://r/2", "reply": "y", "status": "draft", "found": ago(0)}])
        s = self.state()
        self.assertEqual([k for k, _ in s["cards"]], ["knitwit|Reddit|https://r/1", "knitwit|Reddit|https://r/2"])
        self.assertIn('data-url="https://r/2"', s["cards"][1][1])
        self.assertEqual(s["count"], 2)
        self.call("/closed", {})
        self.thread.join(5)

    def test_state_says_what_is_still_looking(self):
        self.assertEqual(self.state()["looking"], [])
        drafts.looking.start(self.t.p, "session", "Reading r/knitting threads")
        self.assertEqual(self.state()["looking"], ["Reading r/knitting threads"])
        self.assertIn(b"Reading r/knitting threads", self.call("/")[1])
        self.call("/closed", {})
        self.thread.join(5)

    def test_a_poll_is_not_a_close_and_does_not_expire_rows(self):
        with mock.patch.object(drafts, "expire") as expire:
            self.state()
        expire.assert_not_called()
        self.call("/closed", {})
        self.thread.join(5)

    def test_unknown_rows_are_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.call("/skip", {"product": "knitwit", "platform": "Reddit", "url": "https://elsewhere"})
        self.call("/closed", {})
        self.thread.join(5)


class RichCopyTest(unittest.TestCase):
    """Copy puts linked HTML on the clipboard beside the Markdown, so a paste
    into Reddit's rich-text box keeps the store links."""

    def test_markdown_links_become_anchors(self):
        out = drafts.rich("Cragbook ([iOS](https://a.example/x?a=1&b=2) and [Android](https://p.example/y))")
        self.assertEqual(out, '<p>Cragbook (<a href="https://a.example/x?a=1&amp;b=2">iOS</a> and '
                              '<a href="https://p.example/y">Android</a>)</p>')

    def test_text_is_escaped_and_paragraphs_kept(self):
        self.assertEqual(drafts.rich("a < b\n\nsecond\n[line](https://l.example)"),
                         '<p>a &lt; b</p><p>second<br><a href="https://l.example">line</a></p>')

    def test_no_html_when_there_are_no_links(self):
        self.assertIsNone(drafts.rich("Plain reply with https://bare.example/url"))

    def test_card_carries_the_html(self):
        row = {"product": "X", "platform": "Reddit", "where": "r/x", "url": "https://r/1", "app": "X",
               "reply_text": "See [iOS](https://a.example)", "found": "2026-10-27"}
        self.assertIn('data-html="&lt;p&gt;See &lt;a href=&quot;https://a.example&quot;&gt;iOS&lt;/a&gt;&lt;/p&gt;"',
                      drafts.card(row, ["X"]))


class WarnOnceTest(unittest.TestCase):
    """The page polls every few seconds, so a draft's check: line prints once, not on every poll."""

    def setUp(self):
        self.t = TempProduct()
        self.t.write("Threads", [{"url": "https://t/1", "author": "a", "reply": "x" * 600, "status": "draft"}])

    def tearDown(self):
        self.t.close()

    def test_check_lines_print_once(self):
        from contextlib import redirect_stderr
        from io import StringIO
        warned, err = set(), StringIO()
        with redirect_stderr(err):
            drafts.state([self.t.p], warned)
            drafts.state([self.t.p], warned)
        self.assertEqual(err.getvalue().count("check:"), 1)
