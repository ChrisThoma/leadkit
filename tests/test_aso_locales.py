"""Keyword fields by language: the parts that don't need the network or claude.

    bin/test
"""
import shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso, aso_locales as L, product  # noqa: E402


def scored(phrase, value):
    return {"phrase": phrase, "value": value}


class StorefrontTableTest(unittest.TestCase):
    def test_table_has_every_storefront(self):
        rows = L.storefronts()
        self.assertGreater(len(rows), 170)
        self.assertIn("United States", [r["country"] for r in rows])

    def test_us_reads_spanish_mexico_but_not_uk_english(self):
        self.assertIn("United States", L.readers("es-MX")[1])
        self.assertIn("Mexico", L.readers("es-MX")[0])
        self.assertNotIn("United States", L.readers("en-GB")[0] + L.readers("en-GB")[1])

    def test_both_spellings_of_simplified_chinese(self):
        self.assertIn("China mainland", L.readers("zh-Hans")[0])
        self.assertIn("Singapore", L.readers("zh-Hans")[1])

    def test_every_locale_has_a_checked_storefront_and_a_reader(self):
        for code, (_, country, _) in L.LOCALES.items():
            self.assertIn(country, aso.STOREFRONTS, code)
            self.assertTrue(any(L.readers(code)), code)


class UnitsTest(unittest.TestCase):
    def test_spaced_languages_split_and_drop_filler(self):
        self.assertEqual(L.units("Reihen zählen mit Nadelspiel", "de-DE"), ["reihen", "zählen", "nadelspiel"])
        self.assertEqual(L.units("reihen-zähler", "de-DE"), ["reihen", "zähler"])
        self.assertEqual(L.units("row counter for knitting", "en-US"), ["row", "counter", "knitting"])

    def test_unspaced_languages_split_on_the_seeds_spaces(self):
        self.assertEqual(L.units("編み物 段数 数える", "ja"), ["編み物", "段数", "数える"])

    def test_short_latin_filler_drops_but_short_hangul_stays(self):
        self.assertEqual(L.units("tricô à mão livre", "pt-BR"), ["tricô", "mão", "livre"])
        self.assertEqual(L.units("뜨개질 단 수", "ko"), ["뜨개질", "단", "수"])

    def test_a_number_is_a_word_the_field_has_to_hold(self):
        # "laine 4 fils" isn't covered by a field holding only "fils".
        self.assertEqual(L.units("laine 4 fils", "fr-FR"), ["laine", "4", "fils"])
        self.assertEqual(L.units("4-ply yarn", "en-US"), ["4", "ply", "yarn"])

    def test_app_in_another_language_is_filler(self):
        self.assertEqual(L.units("뜨개질 앱", "ko"), ["뜨개질"])
        self.assertEqual(L.units("aplikasi mengait", "ms"), ["mengait"])
        self.assertEqual(L.units("aplicație tricotat", "ro"), ["tricotat"])
        self.assertEqual(L.units("編み物 アプリ", "ja"), ["編み物"])

    def test_known_allows_two_letters_of_ending(self):
        vocab = {"masche", "stitch", "row"}
        self.assertTrue(L.known("maschen", vocab))
        self.assertFalse(L.known("stitchify", vocab))
        self.assertTrue(L.known("row", vocab))
        self.assertFalse(L.known("addict", vocab))
        self.assertFalse(L.known("masche44", vocab))


class HintsTest(unittest.TestCase):
    def test_brand_segments_are_dropped(self):
        vocab = {"stricken", "lernen", "maschen", "zähler"}
        self.assertEqual(L.phrases_from_hint("wollwerk - stricken lernen", vocab, "de-DE"), ["stricken lernen"])
        self.assertEqual(L.phrases_from_hint("strickpro: maschen-zähler", vocab, "de-DE"), ["maschen-zähler"])
        self.assertEqual(L.phrases_from_hint("row counter addict lite", {"row", "counter"}, "en-US"), [])

    def test_a_short_fragment_marks_a_brand(self):
        vocab = {"tricô", "mão", "livre"}
        self.assertEqual(L.phrases_from_hint("tricô à mão livre rc", vocab, "pt-BR"), [])
        self.assertEqual(L.phrases_from_hint("tricô à mão livre", vocab, "pt-BR"), ["tricô à mão livre"])

    def test_a_segment_ending_on_filler_is_a_fragment(self):
        # Vietnamese "tạo mẫu al" is "AI pattern maker" with the AI misread; "al" is Spanish filler.
        self.assertEqual(L.phrases_from_hint("tạo mẫu al", {"tạo", "mẫu"}, "vi"), [])

    def test_an_avoided_word_drops_the_segment(self):
        self.assertEqual(L.phrases_from_hint("ai pattern maker", {"ai", "pattern", "maker"}, "en-GB",
                                             avoid={"ai"}), [])
        self.assertEqual(L.phrases_from_hint("pattern maker", {"pattern", "maker"}, "en-GB", avoid={"ai"}),
                         ["pattern maker"])

    def test_a_lone_word_must_be_a_seed_word(self):
        # A one-word suggestion that is a seed word plus two letters is another app's
        # name, not a phrase people type, and must not reach the field.
        vocab = {"tricot", "laine", "maille", "aiguille"}
        for name in ("tricoty", "lainea", "mailleo", "maillea"):
            self.assertEqual(L.phrases_from_hint(name, vocab, "fr-FR"), [], name)
        self.assertEqual(L.phrases_from_hint("tricot", vocab, "fr-FR"), ["tricot"])
        # Inflection still counts inside a longer phrase.
        self.assertEqual(L.phrases_from_hint("laine tricots", vocab, "fr-FR"), ["laine tricots"])

    def test_a_language_can_avoid_its_own_words(self):
        # Catalan is scored in the Spanish store, whose suggestions bring in Spanish diario.
        class P(dict):
            get = dict.get
        p = P(ASO_AVOID={"calendar": "why"}, ASO_AVOID_BY_LOCALE={"ca": ["diario"]})
        self.assertEqual(L.avoid_words(p, "ca"), {"calendar", "diario"})
        self.assertEqual(L.avoid_words(p, "es-ES"), {"calendar"})

    def test_slavic_and_malay_and_are_filler(self):
        self.assertEqual(L.units("трави та спеції", "uk"), ["трави", "спеції"])
        self.assertEqual(L.units("травы и специи", "ru"), ["травы", "специи"])
        self.assertEqual(L.units("herba dan rempah", "ms"), ["herba", "rempah"])

    def test_unspaced_suggestions_only_score(self):
        self.assertEqual(L.phrases_from_hint("編み物カウンター", {"編み物", "カウンター"}, "ja"), [])

    def test_a_suggestion_holding_every_word_counts(self):
        de = L.suggested("de-DE")
        self.assertTrue(de("maschen zähler", ["strickpro: maschen-zähler"]))
        self.assertFalse(de("maschen quiz", ["strickpro: maschen-zähler"]))
        self.assertTrue(L.suggested("ja")("編み物 カウンター", ["編み物カウンタープロ"]))


class PackTest(unittest.TestCase):
    def test_fills_by_value_and_skips_free_words(self):
        field, chosen = L.pack([scored("knitting chart", 50), scored("stitch counter", 40)], {"knitting"}, "en-US")
        self.assertEqual(field, "chart,stitch,counter")
        self.assertEqual(chosen, ["knitting chart", "stitch counter"])

    def test_never_over_the_limit(self):
        phrases = [scored(f"word{i}longer", 10 - i) for i in range(10)]
        field, _ = L.pack(phrases, set(), "en-US", limit=30)
        self.assertLessEqual(len(field), 30)
        self.assertEqual(field, "word0longer,word1longer")

    def test_a_tie_goes_to_the_cheaper_phrase(self):
        field, _ = L.pack([scored("muster stricken", 1), scored("wolle", 1)], set(), "de-DE", limit=20)
        self.assertEqual(field, "wolle")

    def test_unspaced_words_inside_the_name_cost_nothing(self):
        # Japanese titles have no spaces, so "編み物" is free when the subtitle holds "編み物とかぎ針".
        free = {"knitwit：段数カウンター", "編み物とかぎ針の段数を数える"}
        field, _ = L.pack([{"phrase": "編み物 アプリ", "value": 50}, {"phrase": "毛糸", "value": 40}], free, "ja")
        self.assertEqual(field, "毛糸")

    def test_more_app_words_are_filler(self):
        self.assertEqual(L.units("אפליקציה סריגה", "he"), ["סריגה"])
        self.assertEqual(L.units("ऐप बुनाई", "hi"), ["बुनाई"])
        self.assertEqual(L.units("ứng dụng đan", "vi"), ["đan"])

    def test_a_plural_counts_as_its_singular(self):
        field, _ = L.pack([scored("knitting pattern", 5)], {"patterns", "knitting"}, "en-US")
        self.assertEqual(field, "")

    def test_value_discounts_difficulty_without_zeroing(self):
        self.assertGreater(L.value(60, 100), L.value(10, 0))
        self.assertGreater(L.value(0, 0), 0)


class SeedsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("cragbook")
        self.p.dir = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_english_seeds_are_the_keyword_list(self):
        self.assertEqual(L.seeds(self.p, "en-GB"), [k.lower() for k in self.p.need("ASO_KEYWORDS")])

    def test_english_seeds_leave_out_avoided_words(self):
        self.p.cfg.ASO_KEYWORDS = ["climbing log", "crag map", "gear review"]
        self.p.cfg.ASO_AVOID = {"map": "crag maps", "gear": "climbing gear shops"}
        self.assertEqual(L.seeds(self.p, "en-GB"), ["climbing log"])

    def test_the_prompt_names_what_to_avoid(self):
        self.p.cfg.ASO_AVOID = {"map": "crag maps or guidebooks, a navigation search"}
        self.assertIn("crag maps or guidebooks, a navigation search", L.prompt(self.p, "de-DE"))

    def test_cleaning_drops_numbering_but_keeps_a_leading_number(self):
        self.assertEqual(L.clean_seeds("1. 4 finger griff\n- griff\n2) cragbook log\n* kletter tagebuch\n4-finger hangboard\n"),
                         ["4 finger griff", "griff", "cragbook log", "kletter tagebuch", "4-finger hangboard"])

    def test_a_saved_seed_file_wins_and_skips_comments(self):
        path = L.seeds_path(self.p, "de-DE")
        path.parent.mkdir(parents=True)
        path.write_text("# drafted\nKletter Tagebuch\n\nbouldern üben\n")
        self.assertEqual(L.seeds(self.p, "de-DE"), ["kletter tagebuch", "bouldern üben"])

    def test_report_keeps_locales_a_run_did_not_touch(self):
        result = {"locale": "de-DE", "storefront": "de", "field": "klettern", "chosen": ["klettern"],
                  "free": [], "scored": [{"phrase": "klettern", "source": "seed", "popularity": 52,
                                          "difficulty": 20, "value": 47}]}
        L.write_report(self.p, [result])
        L.write_report(self.p, [result | {"locale": "ja", "storefront": "jp", "field": "クライミング"}])
        text = L.report_path(self.p).read_text()
        self.assertIn("## de-DE: German", text)
        self.assertIn("## ja: Japanese", text)
        self.assertLess(text.index("## de-DE"), text.index("## ja"))


# An app's own listing file, kept in its repo (AppStore/fields.py here). The raise
# proves leadkit reads it without running it.
FIELDS_PY = '''"""The listing."""
raise SystemExit("ran the listing file")
NAME = "Knitwit: A Simple Counter"
SUBTITLE = "Count rows in knit and crochet"
KEYWORDS = ("stitch,repeat,"
            "pattern, tracker")
'''


def phrase(text, value=10):
    return {"phrase": text, "source": "seed", "popularity": 50, "difficulty": 20, "value": value}


class ListingFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "AppStore").mkdir()
        (self.tmp / "AppStore" / "fields.py").write_text(FIELDS_PY)
        self.p = product.Product("knitwit")
        self.p.dir = self.tmp / "product"
        self.p.cfg.REPO = str(self.tmp)
        self.p.cfg.ASO_LISTING_FILE = "AppStore/fields.py"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_reads_the_file_without_running_it(self):
        self.assertEqual(L.listing(self.p), {"name": "Knitwit: A Simple Counter",
                                             "subtitle": "Count rows in knit and crochet",
                                             "keywords": "stitch,repeat,pattern, tracker",
                                             "path": "AppStore/fields.py"})

    def test_no_listing_file_configured(self):
        del self.p.cfg.ASO_LISTING_FILE
        self.assertIsNone(L.listing(self.p))

    def test_a_missing_listing_file_fails_loudly(self):
        (self.tmp / "AppStore" / "fields.py").unlink()
        with self.assertRaises(SystemExit):
            L.listing(self.p)

    def test_the_english_us_field_is_the_listings(self):
        scored = [phrase("pattern tracker", 30), phrase("knitwit pattern", 20), phrase("yarn stash", 90)]
        field, chosen, source = L.choose(self.p, "en-US", scored)
        self.assertEqual(field, "stitch,repeat,pattern,tracker")
        self.assertEqual(source, "AppStore/fields.py")
        # knitwit comes from the name; yarn isn't in the field, whatever its value.
        self.assertEqual(chosen, ["pattern tracker", "knitwit pattern"])

    def test_other_english_locales_still_pack_their_own(self):
        field, chosen, source = L.choose(self.p, "en-GB", [phrase("yarn stash", 90)])
        self.assertIsNone(source)
        self.assertEqual(field, "yarn,stash")

    def test_the_name_and_subtitle_come_from_the_listing(self):
        self.p.cfg.ASO_NAME = "Something Else"
        self.assertIn("simple", L.free_words(self.p, "en-US"))
        self.assertNotIn("something", L.free_words(self.p, "en-GB"))

    def test_other_languages_name_and_subtitle_come_from_the_listing_dir(self):
        (self.tmp / "AppStore" / "locales").mkdir()
        (self.tmp / "AppStore" / "locales" / "de-DE.json").write_text(
            '{"name": "Knitwit: Reihenzähler", "subtitle": "Maschen und Muster zählen"}')
        self.p.cfg.ASO_LISTING_DIR = "AppStore/locales"
        self.assertIn("reihenzähler", L.free_words(self.p, "de-DE"))
        self.assertIn("muster", L.free_words(self.p, "de-DE"))
        # A language with no file there indexes only the app's name.
        self.assertEqual(L.free_words(self.p, "fr-FR"), {"knitwit"})

    def test_the_seed_prompt_covers_the_listing_not_the_tracked_phrases(self):
        self.p.cfg.ASO_KEYWORDS = ["yarn stash"]
        text = L.prompt(self.p, "de-DE")
        self.assertIn("stitch, repeat, pattern, tracker", text)
        self.assertIn("Count rows in knit and crochet", text)
        self.assertNotIn("yarn stash", text)

    def test_the_report_says_where_the_field_came_from(self):
        field, chosen, source = L.choose(self.p, "en-US", [phrase("pattern tracker")])
        text = L.section({"locale": "en-US", "storefront": "us", "field": field, "chosen": chosen,
                          "free": [], "scored": [phrase("pattern tracker")], "source": source})
        self.assertIn("AppStore/fields.py", text)


if __name__ == "__main__":
    unittest.main()
