"""leads set: change or add one lead row without a hand-written script. A
script that splits a leads file on newlines breaks multi-line rows, and a sync
after that can cut the file down to a fraction of its rows."""
import io, sys, unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import cli, rows, threads, tsv  # noqa: E402
from helpers import TempProduct  # noqa: E402

R1 = "https://www.reddit.com/r/knitting/comments/abc123/how_do_i/"
T1 = "https://www.threads.com/@someone/post/P1"


class SetTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.t.write("Reddit", [
            {"url": R1, "status": "new", "notes": "Watcher [9].", "kind": "domain"},
            {"url": "https://www.reddit.com/r/crochet/comments/zzz/other/", "status": "new",
             "reply": "line one\n\nline two", "kind": "domain"},
        ])
        self.t.write("Threads", [{"url": T1, "status": "new"}], fields=threads.FIELDS)

    def tearDown(self):
        self.t.close()

    def test_sets_fields_on_the_matching_row_only(self):
        rows.set_row(self.t.p, R1, {"status": "skip", "notes": "destash post"})
        a, b = self.t.read("Reddit")
        self.assertEqual((a["status"], a["notes"]), ("skip", "destash post"))
        self.assertEqual(b["status"], "new")
        self.assertEqual(b["reply"], "line one\n\nline two")  # multi-line cells survive the rewrite

    def test_matches_the_url_loosely(self):
        rows.set_row(self.t.p, "https://old.reddit.com/r/knitting/comments/abc123/how_do_i?utm=x", {"status": "draft"})
        self.assertEqual(self.t.read("Reddit")[0]["status"], "draft")
        rows.set_row(self.t.p, "https://www.threads.net/@someone/post/P1/", {"status": "skip"})
        self.assertEqual(self.t.read("Threads")[0]["status"], "skip")

    def test_plus_equals_appends_to_a_field(self):
        rows.set_row(self.t.p, R1, {"notes+": "Skipped: destash."})
        self.assertEqual(self.t.read("Reddit")[0]["notes"], "Watcher [9]. Skipped: destash.")

    def test_a_multiline_reply_is_kept_whole(self):
        reply = "First paragraph.\n\nSecond, with a [link](https://apps.apple.com/app/id1?ct=reddit)."
        rows.set_row(self.t.p, R1, {"reply": reply, "status": "draft"})
        self.assertEqual(self.t.read("Reddit")[0]["reply"], reply)
        self.assertEqual(len(self.t.read("Reddit")), 2)

    def test_refuses_an_unknown_url(self):
        with self.assertRaisesRegex(SystemExit, "no Reddit row"):
            rows.set_row(self.t.p, "https://www.reddit.com/r/knitting/comments/nope/x/", {"status": "skip"})

    def test_refuses_an_unknown_field_naming_the_header(self):
        with self.assertRaisesRegex(SystemExit, "no column 'needle'.*subreddit"):
            rows.set_row(self.t.p, R1, {"needle": "4mm"})

    def test_refuses_a_bad_status_or_kind(self):
        with self.assertRaisesRegex(SystemExit, "status"):
            rows.set_row(self.t.p, R1, {"status": "done"})
        with self.assertRaisesRegex(SystemExit, "kind"):
            rows.set_row(self.t.p, R1, {"kind": "showcase"})
        self.assertEqual(self.t.read("Reddit")[0]["status"], "new")

    def test_refuses_a_url_that_is_neither_platform(self):
        with self.assertRaisesRegex(SystemExit, "Reddit, Threads or X"):
            rows.set_row(self.t.p, "https://example.com/x", {"status": "skip"})

    def test_add_appends_a_new_row_with_found_and_subreddit(self):
        url = "https://www.reddit.com/r/knittinghelp/comments/new1/cables/"
        rows.set_row(self.t.p, url, {"kind": "domain", "notes": 'From F5Bot ("row counter")'}, add=True)
        new = self.t.read("Reddit")[-1]
        self.assertEqual((new["url"], new["subreddit"], new["status"], new["found"]),
                         (url, "knittinghelp", "new", date.today().isoformat()))

    def test_add_starts_a_threads_file_that_takes_a_kind(self):
        # A new product has no Threads file, and its first hand-logged lead
        # must not fail with "no column 'kind'".
        self.t.p.threads_tsv.unlink()
        rows.set_row(self.t.p, T1, {"kind": "app", "status": "draft"}, add=True)
        self.assertEqual(self.t.read("Threads")[0]["kind"], "app")

    def test_add_needs_a_kind(self):
        with self.assertRaisesRegex(SystemExit, "kind"):
            rows.set_row(self.t.p, "https://www.reddit.com/r/crochet/comments/new2/x/", {"status": "skip"}, add=True)

    def test_add_on_an_existing_row_just_updates_it(self):
        rows.set_row(self.t.p, R1, {"status": "skip", "kind": "domain"}, add=True)
        self.assertEqual(len(self.t.read("Reddit")), 2)
        self.assertEqual(self.t.read("Reddit")[0]["status"], "skip")


class QueryColumnTest(unittest.TestCase):
    """leads set query=...: Threads and X files take the column, Reddit's don't."""

    def setUp(self):
        self.t = TempProduct()
        self.old = [f for f in threads.FIELDS if f != "query"]
        self.reply = "line one\n\n\"quoted\"\tline two"
        self.t.write("Threads", [{"url": T1, "status": "new"},
                                 {"url": "https://www.threads.com/@o/post/P2", "reply": self.reply, "status": "draft"}],
                     fields=self.old)
        self.raw_before = self.t.p.threads_tsv.read_text()
        self.t.write("Reddit", [{"url": R1, "status": "new"}])

    def tearDown(self):
        self.t.close()

    def test_threads_file_gains_the_column_and_keeps_every_row(self):
        rows.set_row(self.t.p, T1, {"query": "drop your app"})
        fields, got = tsv.read(self.t.p.threads_tsv)
        self.assertEqual(fields, self.old + ["query"])
        self.assertEqual([r["query"] for r in got], ["drop your app", ""])
        self.assertEqual(got[1]["reply"], self.reply)
        # The multi-line quoted cell is written exactly as it was.
        quoted = self.raw_before[self.raw_before.index('"line one'):self.raw_before.index('\tdraft')]
        self.assertIn(quoted, self.t.p.threads_tsv.read_text())

    def test_query_plus_appends(self):
        rows.set_row(self.t.p, T1, {"query": "a"})
        rows.set_row(self.t.p, T1, {"query+": "b"})
        self.assertEqual(self.t.read("Threads")[0]["query"], "a b")

    def test_x_file_gains_the_column_too(self):
        x = "https://x.com/someone/status/1"
        tsv.write(self.t.p.x_tsv, ["found", "url", "status"], [{"found": "2026-11-01", "url": x, "status": "new"}])
        rows.set_row(self.t.p, x, {"query": "indie dev"})
        fields, got = tsv.read(self.t.p.x_tsv)
        self.assertEqual((fields, got[0]["query"]), (["found", "url", "status", "query"], "indie dev"))

    def test_reddit_still_refuses_it(self):
        with self.assertRaisesRegex(SystemExit, "no column 'query'"):
            rows.set_row(self.t.p, R1, {"query": "x"})
        self.assertNotIn("query", tsv.read(self.t.p.reddit_tsv)[0])

    def test_other_unknown_columns_are_still_refused_on_threads(self):
        with self.assertRaisesRegex(SystemExit, "no column 'nope'"):
            rows.set_row(self.t.p, T1, {"nope": "x"})
        self.assertNotIn("query", tsv.read(self.t.p.threads_tsv)[0])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.t.write("Reddit", [{"url": R1, "status": "new", "kind": "domain"}])
        self._pick = cli.product.pick
        cli.product.pick = lambda name=None: self.t.p

    def tearDown(self):
        cli.product.pick = self._pick
        self.t.close()

    def test_field_value_pairs_and_stdin_reply(self):
        stdin, sys.stdin = sys.stdin, io.StringIO("Para one.\n\nPara two.\n")
        try:
            cli.main(["set", R1, "status=draft", "reply=-", "notes+=drafted"])
        finally:
            sys.stdin = stdin
        r = self.t.read("Reddit")[0]
        self.assertEqual((r["status"], r["reply"], r["notes"]), ("draft", "Para one.\n\nPara two.", "drafted"))

    def test_a_pair_without_equals_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "field=value"):
            cli.main(["set", R1, "skip"])


if __name__ == "__main__":
    unittest.main()
