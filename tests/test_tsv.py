"""The leads TSVs are rewritten in place by several commands, so a bad row or a
failed write must never cost the rows already there. A file with
tab-padded lines can break its quoting, and a rewrite that stops at the first
bad row would drop every row after it."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from leadkit import tsv  # noqa: E402

FIELDS = ["url", "notes", "status"]


class TsvSafety(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "leads.tsv"

    def test_a_row_with_extra_columns_is_refused_with_its_line(self):
        self.path.write_text("url\tnotes\tstatus\nu1\tok\tnew\nu2\tbroken\tnew\textra\t\n")
        with self.assertRaisesRegex(ValueError, "line 3"):
            tsv.read(self.path)

    def test_rewrite_of_a_broken_file_leaves_it_untouched(self):
        text = "url\tnotes\tstatus\nu1\tok\tnew\nu2\tbroken\tnew\textra\n"
        self.path.write_text(text)
        with self.assertRaises(ValueError):
            tsv.rewrite(self.path, lambda r: r.update(status="skip") or True)
        self.assertEqual(self.path.read_text(), text)

    def test_a_write_that_fails_partway_keeps_the_old_file(self):
        tsv.write(self.path, FIELDS, [{"url": "u1", "notes": "a", "status": "new"}])
        before = self.path.read_text()
        rows = [{"url": "u1", "notes": "a", "status": "skip"}, {"url": "u2", "bogus": "x"}]
        with self.assertRaises(ValueError):
            tsv.write(self.path, FIELDS, rows)
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(list(self.dir.iterdir()), [self.path])

    def test_multiline_cells_round_trip(self):
        rows = [{"url": "u1", "notes": "first\n\nsecond", "status": "draft"}]
        tsv.write(self.path, FIELDS, rows)
        self.assertEqual(tsv.read(self.path), (FIELDS, rows))


if __name__ == "__main__":
    unittest.main()
