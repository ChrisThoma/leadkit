"""leads pitches: roundup authors, app lists and creators to pitch, and which follow-ups are due.

Other people's coverage can sell more than replies, and a pitch nobody tracks
never gets its follow-up.
"""
import sys, unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import cli, pitches, tsv  # noqa: E402
from helpers import TempProduct  # noqa: E402

TODAY = date(2026, 11, 17)


def row(url, **kw):
    return dict.fromkeys(pitches.FIELDS, "") | {"url": url, "target": url.split("/")[2], "status": "todo"} | kw


class TempPitches(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")
        self.p = self.t.p

    def tearDown(self):
        self.t.close()

    def seed(self, *rows):
        tsv.write(pitches.path(self.p), pitches.FIELDS, list(rows))

    def rows(self):
        return tsv.read(pitches.path(self.p))[1]


class DueTest(unittest.TestCase):
    def test_a_sent_pitch_is_due_on_its_followup_date_and_after(self):
        rows = [row("https://a.com/x", status="sent", sent="2026-11-10", followup="2026-11-17"),
                row("https://b.com/x", status="sent", sent="2026-10-27", followup="2026-11-03"),
                row("https://c.com/x", status="sent", sent="2026-11-12", followup="2026-11-19")]
        self.assertEqual([r["url"] for r in pitches.due(rows, TODAY)], ["https://b.com/x", "https://a.com/x"])

    def test_waiting_is_sent_but_not_due_yet(self):
        rows = [row("https://a.com/x", status="sent", sent="2026-11-12", followup="2026-11-19"),
                row("https://b.com/x", status="sent", sent="2026-10-27", followup="2026-11-03"),
                row("https://c.com/x", status="listed", sent="2026-10-01")]
        self.assertEqual([r["url"] for r in pitches.waiting(rows, TODAY)], ["https://a.com/x"])

    def test_a_followed_up_pitch_comes_due_again_to_be_closed(self):
        rows = [row("https://a.com/x", status="followed-up", sent="2026-10-27", followup="2026-11-16")]
        self.assertEqual(len(pitches.due(rows, TODAY)), 1)

    def test_next_up_is_todo_and_drafted_in_file_order(self):
        rows = [row("https://a.com/x", status="skip"), row("https://b.com/x"), row("https://c.com/x", status="drafted"),
                row("https://d.com/x"), row("https://e.com/x")]
        self.assertEqual([r["url"] for r in pitches.next_up(rows, 3)],
                         ["https://b.com/x", "https://c.com/x", "https://d.com/x"])


class TransitionTest(unittest.TestCase):
    def test_sent_fills_sent_today_and_followup_a_week_on(self):
        r = row("https://a.com/x")
        pitches.change(r, {"status": "sent", "code": "ABC123"}, TODAY)
        self.assertEqual((r["sent"], r["followup"], r["code"]), ("2026-11-17", "2026-11-24", "ABC123"))

    def test_sent_keeps_dates_given(self):
        r = row("https://a.com/x")
        pitches.change(r, {"status": "sent", "sent": "2026-10-27"}, TODAY)
        self.assertEqual((r["sent"], r["followup"]), ("2026-10-27", "2026-11-03"))
        r = row("https://b.com/x")
        pitches.change(r, {"status": "sent", "followup": "2026-12-01"}, TODAY)
        self.assertEqual((r["sent"], r["followup"]), ("2026-11-17", "2026-12-01"))

    def test_followed_up_moves_the_next_nudge_a_week_on(self):
        r = row("https://a.com/x", status="sent", sent="2026-10-27", followup="2026-11-03")
        pitches.change(r, {"status": "followed-up"}, TODAY)
        self.assertEqual((r["sent"], r["followup"]), ("2026-10-27", "2026-11-24"))

    def test_a_closed_pitch_has_no_followup(self):
        for status in ("listed", "declined", "no-reply", "skip"):
            r = row("https://a.com/x", status="sent", sent="2026-10-27", followup="2026-11-03")
            pitches.change(r, {"status": status}, TODAY)
            self.assertEqual((r["status"], r["followup"]), (status, ""))

    def test_notes_append_and_bad_values_refuse(self):
        r = row("https://a.com/x", notes="hold")
        pitches.change(r, {"notes+": "until ratings"}, TODAY)
        self.assertEqual(r["notes"], "hold until ratings")
        for bad in ({"status": "posted"}, {"kind": "blog"}, {"views": "3"}):
            with self.assertRaises(SystemExit):
                pitches.change(row("https://a.com/x"), bad, TODAY)


class FileTest(TempPitches):
    def test_add_appends_a_todo_row_and_starts_the_file(self):
        pitches.add(self.p, "https://www.example-blog.com/posts/the-best-knitting-apps",
                    {"target": "Example Blog", "kind": "roundup", "route": "/contact"})
        pitches.add(self.p, "https://example-list.com/best/", {"target": "Example List"})
        rows = self.rows()
        self.assertEqual([(r["target"], r["status"]) for r in rows], [("Example Blog", "todo"), ("Example List", "todo")])
        self.assertEqual(tsv.read(pitches.path(self.p))[0], pitches.FIELDS)

    def test_add_refuses_a_url_already_there(self):
        self.seed(row("https://example-list.com/best/"))
        with self.assertRaises(SystemExit):
            pitches.add(self.p, "https://Example-List.com/best", {"target": "again"})
        self.assertEqual(len(self.rows()), 1)

    def test_set_changes_the_row_and_saves(self):
        self.seed(row("https://a.com/x"), row("https://b.com/x"))
        pitches.set_row(self.p, "https://b.com/x/", {"status": "sent", "code": "ABC123"}, TODAY)
        b = self.rows()[1]
        self.assertEqual((b["status"], b["sent"], b["followup"], b["code"]), ("sent", "2026-11-17", "2026-11-24", "ABC123"))
        self.assertEqual(self.rows()[0]["status"], "todo")

    def test_set_refuses_an_unknown_url(self):
        self.seed(row("https://a.com/x"))
        with self.assertRaises(SystemExit):
            pitches.set_row(self.p, "https://z.com/x", {"status": "sent"}, TODAY)


class ReportTest(TempPitches):
    def test_report_lists_due_then_waiting_then_next_then_counts(self):
        self.seed(row("https://www.example-blog.com/posts/best", target="Example Blog", status="sent",
                      sent="2026-10-27", followup="2026-11-03", route="example-blog.com/contact"),
                  row("https://a.com/x", target="Site A", status="sent", sent="2026-11-12", followup="2026-11-19"),
                  row("https://b.com/x", target="Site B", kind="roundup", route="b.com/contact", fit="lists FretPro"),
                  row("https://c.com/x", target="Site C"),
                  row("https://d.com/x", target="Site D", status="listed"))
        text = pitches.report(self.p, TODAY, todo=1)
        due, waiting, nxt = text.index("Follow up now"), text.index("Awaiting a reply"), text.index("Next to pitch")
        self.assertLess(due, waiting)
        self.assertLess(waiting, nxt)
        self.assertIn("Example Blog", text[due:waiting])
        self.assertIn("due 2026-11-03", text[due:waiting])
        self.assertIn("21 days", text[due:waiting])
        self.assertIn("Site A", text[waiting:nxt])
        self.assertIn("5 days", text[waiting:nxt])
        self.assertIn("Site B", text[nxt:])
        self.assertIn("lists FretPro", text[nxt:])
        self.assertNotIn("Site C", text)
        self.assertIn("todo 2, sent 2, listed 1", text.splitlines()[-1])

    def test_a_product_without_a_file_reports_nothing(self):
        self.assertEqual(pitches.report(self.p, TODAY), "")


class CliTest(TempPitches):
    def setUp(self):
        super().setUp()
        mock.patch.object(cli.product, "pick", return_value=self.p).start()
        mock.patch.object(cli.product, "from_cwd", return_value=self.p).start()

    def tearDown(self):
        mock.patch.stopall()
        super().tearDown()

    def run_cli(self, *argv):
        out = StringIO()
        with redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_add_set_and_report_through_the_command(self):
        self.run_cli("pitches", "add", "https://a.com/x", "target=Site A", "kind=roundup")
        self.run_cli("pitches", "set", "https://a.com/x", "status=sent", "notes+=via form")
        r = self.rows()[0]
        self.assertEqual((r["status"], r["notes"]), ("sent", "via form"))
        self.assertTrue(r["followup"])
        self.assertIn("Site A", self.run_cli("pitches"))

    def test_set_parses_pairs_like_leads_set(self):
        self.seed(row("https://a.com/x"))
        with self.assertRaises(SystemExit):
            self.run_cli("pitches", "set", "https://a.com/x", "nonsense")


if __name__ == "__main__":
    unittest.main()
