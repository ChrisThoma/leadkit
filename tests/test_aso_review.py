"""The Wiktionary check on keyword fields, without the network.

    bin/test
"""
import shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso_locales, aso_review as R, product  # noqa: E402

# Knitwit's subject: a knitting row counter.
KNIT = R.topic(["knit", "yarn", "stitch", "row", "count"])


def reply(code, *definitions):
    return {code: [{"partOfSpeech": "Noun", "definitions": [{"definition": d} for d in definitions]}]}


class ReviewTest(unittest.TestCase):
    def test_meanings_come_from_the_locales_language_only(self):
        entry = reply("da", "indefinite plural of <a>row</a>") | reply("fr", "to notice")
        self.assertEqual(R.meanings(entry, "da"), ["indefinite plural of row"])
        self.assertEqual(R.meanings(entry, "de-DE"), [])
        self.assertEqual(R.meanings({"httpCode": 404}, "fi"), [])

    def test_norwegian_and_chinese_codes(self):
        self.assertEqual(R.meanings(reply("other", "to knit"), "no"), ["to knit"])
        self.assertEqual(R.meanings(reply("zh", "yarn"), "zh-Hant"), ["yarn"])

    def test_flags(self):
        self.assertEqual(R.verdict("appi", ["father-in-law"], subject=KNIT), "off topic?")
        self.assertEqual(R.verdict("stricken", ["to knit"], subject=KNIT), "")
        self.assertEqual(R.verdict("ωτοδιέγερση", []), "no entry")
        self.assertEqual(R.verdict("purlwise", [], keep={"purlwise"}), "")
        self.assertEqual(R.verdict("编织计数", [], "zh-Hans"), "")
        self.assertEqual(R.verdict("counter", [], "id", english=True), "English word")
        self.assertEqual(R.verdict("llana", [], "ca", failed=True), "lookup failed")

    def test_learning_words_pass_for_every_product(self):
        self.assertEqual(R.verdict("lernen", ["to learn"]), "")
        self.assertEqual(R.verdict("stricken", ["to knit"]), "off topic?")

    def test_check_keeps_field_order(self):
        fake = {"neule": reply("fi", "knitting"), "appi": reply("fi", "father-in-law")}
        rows = R.check("fi", "neule,appi,xyz", look=fake.get, subject=KNIT)
        self.assertEqual([r["flag"] for r in rows], ["", "off topic?", "no entry"])

    def test_an_inflection_takes_the_lemmas_meaning(self):
        fake = {"hilos": reply("es", "plural of <a>hilo</a>"), "hilo": reply("es", "yarn, thread", "wire")}
        rows = R.check("es-MX", "hilos", look=fake.get, subject=KNIT)
        self.assertEqual(rows[0]["flag"], "")
        self.assertEqual(rows[0]["meanings"][0], "hilo: yarn, thread")

    def test_the_other_bucket_clears_but_never_flags(self):
        fake = {"pletenje": reply("other", "knitting"), "vaje": reply("other", "hate, anger")}
        rows = R.check("sl", "pletenje,vaje", look=fake.get, subject=KNIT)
        self.assertEqual([r["flag"] for r in rows], ["", "no entry"])

    def test_a_failed_lookup_says_so(self):
        rows = R.check("ca", "llana", look=lambda w: R.FAILED)
        self.assertEqual(rows[0]["flag"], "lookup failed")


class FieldsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("cragbook")
        self.p.dir = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_fields_read_back_from_the_report(self):
        result = {"locale": "fi", "storefront": "fi", "field": "kiipeily,appi", "chosen": [], "free": [],
                  "scored": []}
        aso_locales.write_report(self.p, [result, result | {"locale": "de-DE", "field": "klettern"}])
        self.assertEqual(R.fields(self.p), {"fi": "kiipeily,appi", "de-DE": "klettern"})

    def test_run_uses_the_products_topic_and_keep_list(self):
        result = {"locale": "fi", "storefront": "fi", "field": "kiipeily,appi,hangboard", "chosen": [],
                  "free": [], "scored": []}
        aso_locales.write_report(self.p, [result])
        fake = {"kiipeily": reply("fi", "climbing"), "appi": reply("fi", "father-in-law")}
        checked = R.run(self.p, look=fake.get)
        self.assertEqual([r["flag"] for r in checked["fi"]], ["", "off topic?", ""])

    def test_likely_mistakes_come_before_unverified_words(self):
        def row(word, flag):
            return {"word": word, "meanings": [], "flag": flag}
        checked = {"fi": [row("kiipeily", ""), row("appi", "off topic?"), row("kiipeilyloki", "no entry")],
                   "id": [row("climbing", "English word"), row("panjat", "lookup failed")]}
        text = R.write(self.p, checked).read_text()
        first, rest = text.split("## Look at these first")[1].split("## Unverified")
        unverified = rest.split("\n## ")[0]
        self.assertIn("appi", first)
        self.assertIn("climbing", first)
        self.assertNotIn("kiipeilyloki", first)
        self.assertIn("kiipeilyloki", unverified)
        self.assertIn("panjat", unverified)
        self.assertNotIn("appi", unverified)
        self.assertNotIn("kiipeily (", first + unverified)


if __name__ == "__main__":
    unittest.main()
