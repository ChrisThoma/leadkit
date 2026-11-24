"""aso export: the fields to paste into App Store Connect, and which ones are pasted.

    bin/test
"""
import shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso_export as E, aso_locales, product  # noqa: E402


def result(locale, field):
    return {"locale": locale, "storefront": "x", "field": field, "chosen": [], "free": [], "scored": []}


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("cragbook")
        self.p.dir = self.tmp
        aso_locales.write_report(self.p, [result("de-DE", "klettern,bouldern"), result("fi", "kiipeily,boulderointi")])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_nothing_is_pasted_at_first(self):
        text = E.render(self.p)
        self.assertIn("de-DE  German  (not pasted)\nklettern,bouldern\n", text)
        self.assertIn("fi  Finnish  (not pasted)\nkiipeily,boulderointi\n", text)

    def test_marking_records_the_field_as_pasted(self):
        E.mark(self.p, ["de-DE"], today="2026-10-29")
        text = E.render(self.p)
        self.assertIn("de-DE  German  (pasted 2026-10-29)", text)
        self.assertIn("fi  Finnish  (not pasted)", text)

    def test_a_field_changed_since_pasting_says_so(self):
        E.mark(self.p, ["all"], today="2026-10-29")
        aso_locales.write_report(self.p, [result("fi", "kiipeily,reitit")])
        self.assertIn("fi  Finnish  (changed since pasted 2026-10-29)", E.render(self.p))
        self.assertIn("de-DE  German  (pasted 2026-10-29)", E.render(self.p))

    def test_todo_leaves_out_what_is_already_pasted(self):
        E.mark(self.p, ["de-DE"], today="2026-10-29")
        text = E.render(self.p, todo=True)
        self.assertNotIn("klettern", text)
        self.assertIn("kiipeily", text)

    def test_only_some_locales(self):
        text = E.render(self.p, only=["fi"])
        self.assertNotIn("klettern", text)

    def test_marking_a_locale_without_a_field_fails(self):
        with self.assertRaises(SystemExit):
            E.mark(self.p, ["ja"], today="2026-10-29")
        self.assertFalse(E.path(self.p).exists())

    def test_the_listing_files_locale_is_pushed_not_pasted(self):
        aso_locales.write_report(self.p, [result("en-US", "climbing,log")])
        (self.tmp / "AppStore").mkdir()
        (self.tmp / "AppStore" / "fields.py").write_text('NAME = "A"\nSUBTITLE = "B"\nKEYWORDS = "climbing,log"\n')
        self.p.cfg.REPO = str(self.tmp)
        self.p.cfg.ASO_LISTING_FILE = "AppStore/fields.py"
        self.assertTrue(E.states(self.p)["en-US"].startswith("from AppStore/fields.py"))
        self.assertFalse(E.is_open(E.states(self.p)["en-US"]))
        self.assertTrue(E.is_open(E.states(self.p)["fi"]))
        self.assertNotIn("climbing,log", E.render(self.p, todo=True))
        self.assertIn("2 not pasted", E.render(self.p))


if __name__ == "__main__":
    unittest.main()
