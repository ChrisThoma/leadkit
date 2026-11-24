"""aso export --asc / --play: the app's listing files turned into what each store's tools read.

    bin/test
"""
import json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso_listing as L, aso_locales, product  # noqa: E402

FIELDS = '''NAME = "Knitwit: A Simple Counter"
SUBTITLE = "Count rows in knit and crochet"
PROMO = "Never lose your place in a pattern."
KEYWORDS = "stitch,repeat"
DESCRIPTION = """Knitwit is a row counter."""
WHATS_NEW = """New: repeat counters."""
SUPPORT_URL = "https://example.com/support"
PRIVACY_URL = "https://example.com/privacy"
print("runs a check table")
'''


def result(locale, field):
    return {"locale": locale, "storefront": "x", "field": field, "chosen": [], "free": [], "scored": []}


def copy(name="Knitwit : compteur de rangs", **extra):
    return {"name": name, "subtitle": "Tricot et crochet", "promotionalText": "Comptez.",
            "description": "Knitwit est un compteur de rangs.", "whatsNew": "Nouveau : répétitions.", **extra}


class ListingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("knitwit")
        self.p.dir = self.tmp / "product"
        self.p.cfg.REPO = str(self.tmp / "repo")
        self.p.cfg.ASO_LISTING_FILE = "AppStore/fields.py"
        self.p.cfg.ASO_LISTING_DIR = "AppStore/listing"
        self.p.cfg.ASO_PLAY_METADATA_DIR = "android/fastlane/metadata/android"
        (self.tmp / "repo" / "AppStore" / "listing").mkdir(parents=True)
        (self.tmp / "repo" / "AppStore" / "fields.py").write_text(FIELDS)
        aso_locales.write_report(self.p, [result("en-GB", "stitch,purl"), result("en-AU", "stitch,purl"),
                                          result("en-CA", "stitch,purl"), result("fr-FR", "tricot,laine")])
        self.out = self.tmp / "asc"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def put(self, locale, data):
        (self.tmp / "repo" / "AppStore" / "listing" / f"{locale}.json").write_text(json.dumps(data))

    def read(self, *parts):
        return json.loads(self.out.joinpath(*parts).read_text())

    def test_en_us_comes_from_the_listing_file_and_others_from_their_json(self):
        self.put("fr-FR", copy())
        self.assertEqual(L.build_asc(self.p, "1.3", self.out), [])
        self.assertEqual(self.read("app-info", "en-US.json")["name"], "Knitwit: A Simple Counter")
        self.assertEqual(self.read("app-info", "en-US.json")["privacyPolicyUrl"], "https://example.com/privacy")
        self.assertEqual(self.read("version", "1.3", "en-US.json")["keywords"], "stitch,repeat")
        self.assertEqual(self.read("app-info", "fr-FR.json")["name"], "Knitwit : compteur de rangs")
        self.assertEqual(self.read("version", "1.3", "fr-FR.json")["supportUrl"], "https://example.com/support")

    def test_keywords_come_from_locales_md_not_the_json(self):
        self.put("fr-FR", copy(keywords="stale,field"))
        L.build_asc(self.p, "1.3", self.out)
        self.assertEqual(self.read("version", "1.3", "fr-FR.json")["keywords"], "tricot,laine")

    def test_an_english_variant_without_its_own_file_reuses_en_us_copy(self):
        L.build_asc(self.p, "1.3", self.out)
        gb = self.read("version", "1.3", "en-GB.json")
        self.assertEqual(gb["description"], "Knitwit is a row counter.")
        self.assertEqual(gb["whatsNew"], "New: repeat counters.")
        self.assertEqual(gb["keywords"], "stitch,purl")

    def test_an_english_variant_with_its_own_file_uses_it(self):
        self.put("en-GB", copy(name="Knitwit: A Simple Counter", description="Customisable."))
        L.build_asc(self.p, "1.3", self.out)
        self.assertEqual(self.read("version", "1.3", "en-GB.json")["description"], "Customisable.")

    def test_problems_are_reported_and_the_rest_still_written(self):
        self.put("fr-FR", copy(name="Compteur : un nom bien trop long pour Apple"))
        self.put("de-DE", {k: v for k, v in copy(name="Knitwit: Reihen").items() if k != "whatsNew"})
        problems = L.build_asc(self.p, "1.3", self.out)
        self.assertIn("fr-FR: name is 43/30", problems)
        self.assertIn("fr-FR: name doesn't start with Knitwit", problems)
        self.assertIn("de-DE: no whatsNew", problems)
        self.assertIn("de-DE: no keyword field in locales.md", problems)
        self.assertTrue((self.out / "app-info" / "en-US.json").exists())

    def test_dashes_in_copy_are_a_problem(self):
        self.put("fr-FR", copy(description="Un compteur — rapide."))
        self.assertIn("fr-FR: dash in copy", L.build_asc(self.p, "1.3", self.out))

    def test_play_files_go_under_plays_language_code(self):
        self.put("he", copy(name="Knitwit", play={"title": "Knitwit", "shortDescription": "קצר",
                                                    "fullDescription": "ארוך"}))
        self.assertEqual(L.build_play(self.p), [])
        folder = self.tmp / "repo" / "android/fastlane/metadata/android/iw-IL"
        self.assertEqual((folder / "short_description.txt").read_text(), "קצר\n")
        self.assertEqual((folder / "title.txt").read_text(), "Knitwit\n")

    def test_play_without_copy_or_a_folder_says_so(self):
        self.put("fr-FR", copy())
        self.assertEqual(L.build_play(self.p), ["fr-FR: no play copy"])
        self.p.cfg.ASO_PLAY_METADATA_DIR = None
        with self.assertRaises(SystemExit):
            L.build_play(self.p)

    def test_play_notes_are_one_file_per_play_language(self):
        self.put("he", copy(name="Knitwit", whatsNew="חדש"))
        self.put("fr-FR", copy())
        out = self.tmp / "notes"
        self.assertEqual(L.build_play_notes(self.p, out), [])
        self.assertEqual((out / "en-US.txt").read_text(), "New: repeat counters.\n")
        self.assertEqual((out / "iw-IL.txt").read_text(), "חדש\n")
        self.assertEqual((out / "fr-FR.txt").read_text(), "Nouveau : répétitions.\n")
        self.assertEqual((out / "en-GB.txt").read_text(), "New: repeat counters.\n")
        self.assertFalse((out / "he.txt").exists())

    def test_play_notes_need_no_play_copy_or_metadata_folder(self):
        # A product whose Play listing is edited by hand has neither.
        self.p.cfg.ASO_PLAY_METADATA_DIR = None
        self.put("fr-FR", copy())
        self.assertEqual(L.build_play_notes(self.p, self.tmp / "notes"), [])

    def test_play_notes_report_a_line_that_is_missing_or_too_long(self):
        self.put("fr-FR", copy(whatsNew=""))
        self.put("de-DE", copy(whatsNew="x" * 501))
        out = self.tmp / "notes"
        self.assertEqual(L.build_play_notes(self.p, out), ["de-DE: whatsNew is 501/500", "fr-FR: whatsNew empty"])
        self.assertFalse((out / "fr-FR.txt").exists())
        self.assertFalse((out / "de-DE.txt").exists())

    def test_play_notes_come_from_play_whats_new_when_english_has_one(self):
        fields = self.tmp / "repo" / "AppStore" / "fields.py"
        fields.write_text(FIELDS + 'PLAY_WHATS_NEW = """New: a stitch marker."""\n')
        self.put("fr-FR", copy(playWhatsNew="Nouveau : un marqueur de mailles."))
        self.put("de-DE", copy())
        out = self.tmp / "notes"
        self.assertEqual(L.build_play_notes(self.p, out), ["de-DE: playWhatsNew empty"])
        self.assertEqual((out / "en-US.txt").read_text(), "New: a stitch marker.\n")
        self.assertEqual((out / "en-GB.txt").read_text(), "New: a stitch marker.\n")
        self.assertEqual((out / "fr-FR.txt").read_text(), "Nouveau : un marqueur de mailles.\n")
        self.assertFalse((out / "de-DE.txt").exists(), "no fallback to the iOS whatsNew")


if __name__ == "__main__":
    unittest.main()
