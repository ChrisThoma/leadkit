"""leads threads-yield: which searches found leads whose replies got views.

    bin/test
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import threads, tsv, yields  # noqa: E402
from helpers import TempProduct  # noqa: E402

FIELDS = threads.FIELDS + threads.ID_FIELDS
ME = "https://www.threads.com/@mythreadshandle/post/"


def lead(n, query="", status="new", found="2026-11-10", **more):
    return {"found": found, "url": f"https://www.threads.com/@a/post/L{n}", "status": status,
            "query": query, "kind": "domain"} | more


def reply(code, views, rid="", posted="2026-11-11 10:00"):
    return {"posted": posted, "url": ME + code, "id": rid or f"id-{code}", "text": f"text {code}",
            "views": str(views), "likes": "0", "replies": "0", "reposts": "0", "quotes": "0", "read": "2026-11-18"}


def draft(n, text, found="2026-11-10", status="replied", **more):
    return lead(n, "q", status, found=found, reply=text, **more)


class JoinTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")

    def tearDown(self):
        self.t.close()

    def join(self, rows, replies, others=()):
        self.t.write("Threads", rows, fields=FIELDS)
        return yields.Join([self.t.p, *others], replies)

    def text_reply(self, code, text, posted="2026-11-11 10:00"):
        return reply(code, 10, posted=posted) | {"text": text[:80]}

    def test_shortcode_ignores_host_query_and_trailing_slash(self):
        for url in ("https://www.threads.net/@mythreadshandle/post/R1/?xmt=abc", ME + "R1", ME + "R1/"):
            self.assertEqual(yields.code_of(url), "R1", url)
        self.assertEqual(yields.code_of("https://example.com/none"), "")

    def test_found_by_the_reply_note(self):
        rows = [lead(1, status="posted", notes="Reply: https://www.threads.net/@mythreadshandle/post/R2/?x=1 hi")]
        j = self.join(rows, [reply("R1", 5), reply("R2", 9)])
        self.assertEqual(j.of(j.rows["cragbook"][0])["views"], "9")

    def test_found_by_reply_id_when_the_note_is_missing(self):
        j = self.join([lead(1, status="posted", reply_id="77")], [reply("R1", 5, rid="77")])
        self.assertEqual(j.of(j.rows["cragbook"][0])["views"], "5")

    def test_no_reply_found(self):
        j = self.join([lead(1, status="posted", notes=f"Reply: {ME}ZZ", reply_id="nope"), lead(2, status="posted")],
                      [reply("R1", 5)])
        self.assertEqual([j.of(r) for r in j.rows["cragbook"]], [None, None])

    def test_a_unique_text_match(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        j = self.join([draft(1, pitch)], [self.text_reply("R1", pitch), self.text_reply("R2", "Totally unrelated words here")])
        self.assertEqual(j.of(j.rows["cragbook"][0])["url"], ME + "R1")
        self.assertEqual(len(j.by_text), 1)

    def test_a_quoted_draft_edited_by_hand_still_matches(self):
        draft_text = '"Cragbook keeps your sends and grades in one log, with a link."'
        posted = "Cragbook keeps your sends & grades in one log -- with a link!"
        j = self.join([draft(1, draft_text)], [self.text_reply("R1", posted)])
        self.assertIsNotNone(j.of(j.rows["cragbook"][0]))

    def test_a_different_reply_does_not_match(self):
        j = self.join([draft(1, "Cragbook keeps your sends and grades in one log.")],
                      [self.text_reply("R1", "I finally sent my project at the crag yesterday and it felt great")])
        self.assertIsNone(j.of(j.rows["cragbook"][0]))

    def test_the_same_pitch_pairs_by_date(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        rows = [draft(1, pitch, found="2026-11-10"), draft(2, pitch, found="2026-11-14")]
        replies = [self.text_reply("R2", pitch, "2026-11-14 12:00"), self.text_reply("R1", pitch, "2026-11-10 12:00")]
        j = self.join(rows, replies)
        self.assertEqual([j.of(r)["url"] for r in j.rows["cragbook"]], [ME + "R1", ME + "R2"])

    def test_with_none_after_the_closest_before_is_taken(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        j = self.join([draft(1, pitch, found="2026-11-14")],
                      [self.text_reply("R1", pitch, "2026-11-01 12:00"), self.text_reply("R2", pitch, "2026-11-12 12:00")])
        self.assertEqual(j.of(j.rows["cragbook"][0])["url"], ME + "R2")

    def test_an_explicit_link_wins_and_its_reply_is_not_reused(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        rows = [draft(1, pitch, found="2026-11-09"), draft(2, pitch, found="2026-11-10", notes=f"Reply: {ME}R1")]
        j = self.join(rows, [self.text_reply("R1", pitch, "2026-11-10 09:00")])
        first, second = j.rows["cragbook"]
        self.assertEqual(j.of(second)["url"], ME + "R1")
        self.assertIsNone(j.of(first))
        self.assertEqual(j.by_text, set())

    def test_a_row_without_draft_text_stays_blind(self):
        j = self.join([lead(1, status="posted")], [self.text_reply("R1", "anything at all, really")])
        self.assertIsNone(j.of(j.rows["cragbook"][0]))

    def test_open_rows_are_not_text_matched(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        j = self.join([draft(1, pitch, status="draft")], [self.text_reply("R1", pitch)])
        self.assertIsNone(j.of(j.rows["cragbook"][0]))

    def test_a_reply_is_used_once_across_products(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        other = TempProduct("knitwit")
        try:
            other.write("Threads", [draft(2, pitch, found="2026-11-12")], fields=FIELDS)
            j = self.join([draft(1, pitch, found="2026-11-10")], [self.text_reply("R1", pitch)], others=[other.p])
            self.assertIsNotNone(j.of(j.rows["cragbook"][0]))
            self.assertIsNone(j.of(j.rows["knitwit"][0]))
        finally:
            other.close()


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")
        rows = [
            lead(1, "what are you building", "posted", notes=f"Reply: {ME}R1"),
            lead(2, "what are you building", "replied", notes=f"Reply: {ME}R2"),
            lead(3, "what are you building", "posted", notes=f"Reply: {ME}R3"),
            lead(4, "what are you building", "posted", notes="posted by hand"),   # no reply recorded
            lead(5, "what are you building", "skip"),
            lead(6, "learning to boulder", "posted", reply_id="id-R4", kind="app"),
            lead(7, "", "posted", notes=f'Found by "drop your app". Reply: {ME}R5'),
        ] + [lead(10 + i, "chalk", "skip") for i in range(8)] + [lead(20, "old", "skip", found="2026-10-01")]
        self.t.write("Threads", rows, fields=FIELDS)
        self.path = self.t.tmp / "threads-replies.tsv"
        tsv.write(self.path, threads.REPLIES_FIELDS, [
            reply("R1", 100), reply("R2", 20), reply("R3", 60), reply("R4", 7), reply("R5", 300),
            reply("X1", 500, posted="2026-11-12 09:00"), reply("X2", 1)])

    def tearDown(self):
        self.t.close()

    def report(self, **kw):
        return yields.report([self.t.p], self.path, **kw)

    def line(self, out, start):
        return next(l for l in out.splitlines() if l.strip().startswith(start))

    def test_query_table_numbers(self):
        out = self.report()
        # found 5, posted 4, seen 3 (R4 of the byhand row is unknown), median of 100/20/60, best 100, two >= 50
        self.assertEqual(self.line(out, "what are you building").split()[-6:], ["5", "4", "3", "60", "100", "2"])
        self.assertEqual(self.line(out, "learning to boulder").split()[-6:], ["1", "1", "1", "7", "7", "0"])

    def test_notes_give_the_query_when_the_column_is_empty(self):
        self.assertEqual(self.line(self.report(), "drop your app").split()[-6:], ["1", "1", "1", "300", "300", "1"])

    def test_rows_sort_by_posted_then_found(self):
        out = self.report()
        at = {n: out.index(f"\n  {n} ") for n in ("what are you building", "learning to boulder", "drop your app",
                                                   "chalk", "old")}
        self.assertLess(at["what are you building"], at["learning to boulder"])
        self.assertLess(at["drop your app"], at["chalk"])  # one posted beats eight found, none posted
        self.assertLess(at["chalk"], at["old"])  # same posted, more found

    def test_min_views_changes_the_last_column(self):
        self.assertEqual(self.line(self.report(min_views=90), "what are you building").split()[-1], "1")

    def test_kind_table(self):
        out = self.report()
        self.assertIn("By kind", out)
        self.assertEqual(self.line(out.split("By kind")[1], "app").split()[1:3], ["1", "1"])

    def test_never_posted_from_needs_eight_leads(self):
        out = self.report()
        self.assertIn("Never posted from: chalk (8)", out)
        self.assertNotIn("what are you building (", out.split("Never posted from:")[1].splitlines()[0])

    def test_posted_rows_without_a_reply(self):
        self.assertIn("1 posted row(s) have no reply found; 0 joined by matching the draft text", self.report())

    def test_since_filters_by_found(self):
        self.assertNotIn("\n  old ", self.report(since="2026-11-01"))
        self.assertIn("\n  old ", self.report())

    def test_unmatched_replies_and_the_top_five(self):
        out = self.report()
        self.assertIn("2 of 7 replies matched no lead", out)
        top = out.split("matched no lead")[1].splitlines()
        self.assertIn("500", top[1])
        self.assertIn(ME + "X1", top[1])
        self.assertIn("1", top[2])

    def test_all_puts_a_combined_table_first_and_unmatched_once(self):
        other = TempProduct("knitwit")
        try:
            other.write("Threads", [lead(1, "x", "posted", notes=f"Reply: {ME}X1")], fields=FIELDS)
            out = yields.report([self.t.p, other.p], self.path)
            self.assertTrue(out.startswith("All products"))
            self.assertEqual(out.count("matched no lead"), 1)
            self.assertIn("1 of 7 replies matched no lead", out)
        finally:
            other.close()

    def test_not_recorded_is_never_listed_as_never_posted(self):
        self.t.write("Threads", [lead(i, "", "skip") for i in range(9)], fields=FIELDS)
        out = self.report()
        self.assertIn("(not recorded)", out)
        self.assertIn("Never posted from: none", out)

    def test_the_report_counts_text_joined_rows(self):
        pitch = "Try Cragbook, it keeps every send and grade in one log so you can see a plateau coming."
        self.t.write("Threads", [draft(1, pitch)], fields=FIELDS)
        tsv.write(self.path, threads.REPLIES_FIELDS, [reply("R1", 40) | {"text": pitch[:80]}])
        out = self.report()
        self.assertIn("0 posted row(s) have no reply found; 1 joined by matching the draft text", out)
        self.assertIn("0 of 1 replies matched no lead", out)

    def test_a_product_with_no_threads_leads(self):
        self.t.p.threads_tsv.unlink()
        self.assertIn("no Threads leads", self.report())

    def test_missing_replies_file_still_reports(self):
        self.path.unlink()
        self.assertIn("what are you building", self.report())


if __name__ == "__main__":
    unittest.main()
