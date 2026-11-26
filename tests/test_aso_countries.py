"""Ranks in the storefronts a product sells in beyond the US (ASO_COUNTRIES), without the network."""
import shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso, aso_cli, aso_export, aso_locales, product, tsv  # noqa: E402


def offline(*a, **k):
    raise AssertionError(f"a test reached the network: {a[:1]}")


def setUpModule():
    global real_fetch
    real_fetch, aso.fetch = aso.fetch, offline


def tearDownModule():
    aso.fetch = real_fetch


def locale_row(day, locale, phrase, popularity="0", difficulty="", in_field="yes"):
    return {"date": day, "locale": locale, "storefront": aso_locales.LOCALES[locale][1], "phrase": phrase,
            "source": "seed", "popularity": popularity, "typed": "", "difficulty": difficulty, "in_field": in_field}


def rank_row(day, country, keyword, store=">12", api=">200"):
    return dict.fromkeys(aso.FIELDS, "") | {"date": day, "country": country, "keyword": keyword,
                                            "store_rank": store, "api_rank": api}


class TempAso(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("cragbook")
        self.p.dir = self.tmp
        (self.tmp / "aso").mkdir()
        self.p.cfg.ASO_COUNTRIES = ["de", "au"]
        tsv.write(aso_export.path(self.p), aso_export.FIELDS, [{"date": "2026-10-30", "locale": "de-DE", "field": "x"}])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def locales(self, rows):
        tsv.write(self.tmp / "aso" / "locale-keywords.tsv", aso_locales.FIELDS, rows)


class LocaleForTest(unittest.TestCase):
    def test_each_storefront_reads_its_first_listed_localization(self):
        found = {c: aso_locales.locale_for(c) for c in ["de", "jp", "br", "cz", "dk", "ua", "th", "au", "ca", "es"]}
        self.assertEqual(found, {"de": "de-DE", "jp": "ja", "br": "pt-BR", "cz": "cs", "dk": "da", "ua": "uk",
                                 "th": "th", "au": "en-AU", "ca": "en-CA", "es": "es-ES"})
        self.assertIsNone(aso_locales.locale_for("zz"))


class TargetedTest(TempAso):
    def test_latest_run_in_field_phrases_once_each_most_valuable_first(self):
        self.locales([
            locale_row("2026-10-29", "de-DE", "alte phrase", "100", "0"),
            locale_row("2026-10-30", "de-DE", "kletter tagebuch", "32", "98"),
            locale_row("2026-10-30", "de-DE", "bouldern lernen", "52", "27"),
            locale_row("2026-10-30", "de-DE", "bouldern quiz"),
            locale_row("2026-10-30", "de-DE", "kletterschuhe test", "90", "0", in_field=""),
            locale_row("2026-10-30", "fr-FR", "carnet escalade", "61", "10"),
            # The same locale run twice in a day appends the same rows again.
            locale_row("2026-10-30", "de-DE", "bouldern lernen", "52", "27"),
        ])
        self.assertEqual(aso_locales.targeted(self.p, "de-DE"), ["bouldern lernen", "kletter tagebuch", "bouldern quiz"])
        self.assertEqual(aso_locales.targeted(self.p, "de-DE", limit=2), ["bouldern lernen", "kletter tagebuch"])
        self.assertEqual(aso_locales.targeted(self.p, "ja"), [])


class KeywordsTest(TempAso):
    def test_a_tracked_storefront_uses_its_languages_phrases(self):
        self.locales([locale_row("2026-10-30", "de-DE", "bouldern lernen", "52", "27")])
        self.assertEqual(aso.keywords(self.p, "de"), ["bouldern lernen"])
        self.assertTrue(aso.localized(self.p, "de"))

    def test_english_storefronts_reuse_the_english_keywords(self):
        english = self.p.need("ASO_KEYWORDS")
        self.assertEqual(aso.keywords(self.p, "au"), english[:aso.COUNTRY_PHRASES])
        self.assertEqual(aso.keywords(self.p, "us"), english)
        self.assertFalse(aso.localized(self.p, "au"))

    def test_a_language_not_on_the_store_keeps_the_english_keywords_and_is_skipped(self):
        aso_export.path(self.p).unlink()
        self.assertEqual(aso.countries(self.p), ["au"])
        self.assertEqual(aso.keywords(self.p, "de"), self.p.need("ASO_KEYWORDS"))
        self.assertFalse(aso.localized(self.p, "de"))

    def test_check_ranks_the_country_phrases_without_hints(self):
        self.locales([locale_row("2026-10-30", "de-DE", "bouldern lernen", "52", "27")])
        calls = []
        real, aso.check_keyword = aso.check_keyword, lambda term, *a, with_hints=True: (
            calls.append((term, a[2], with_hints)) or rank_row("2026-11-17", a[2], term))
        try:
            aso.check(self.p, "de", save=False)
            aso.check(self.p, "au", only=["bouldering"], save=False)
        finally:
            aso.check_keyword = real
        self.assertEqual(calls, [("bouldern lernen", "de", False), ("bouldering", "au", True)])

    def test_a_storefront_with_no_phrases_is_skipped(self):
        self.locales([])
        self.assertEqual(aso.check(self.p, "de", save=False), [])


class AllTest(unittest.TestCase):
    def run_all(self, *extra):
        a, b, c = (product.Product(n) for n in ("cragbook", "knitwit", "mossling"))
        for x in (a, b, c):
            if hasattr(x.cfg, "ASO_COUNTRIES"):
                delattr(x.cfg, "ASO_COUNTRIES")  # use the shared list in settings
        on_store = {"cragbook": {"fr-FR": {}, "de-DE": {}}, "knitwit": {"fr-FR": {}, "de-DE": {}}, "mossling": {}}
        calls = []
        real = product.everything, aso.check, aso.summary, aso_export.pasted, getattr(product.settings, "ASO_COUNTRIES", None)
        product.everything = lambda: [a, b, c]
        aso.check = lambda p, country, **k: calls.append((p.name, country))
        aso.summary = lambda p: ""
        aso_export.pasted = lambda p: on_store[p.name]
        product.settings.ASO_COUNTRIES = ["fr", "de", "au"]
        try:
            aso_cli.main(["check", "--all", "--dry-run", *extra])
        finally:
            product.everything, aso.check, aso.summary, aso_export.pasted, product.settings.ASO_COUNTRIES = real
        return calls

    def test_every_product_in_the_us_and_every_shared_storefront_it_has_a_language_for(self):
        calls = self.run_all()
        for name in ("cragbook", "knitwit"):
            self.assertEqual([c for n, c in calls if n == name], ["us", "fr", "de", "au"])
        self.assertEqual([c for n, c in calls if n == "mossling"], ["us", "au"])

    def test_named_storefronts_only(self):
        self.assertEqual([x for x in self.run_all("-c", "fr", "au") if x[0] != "mossling"],
                         [("cragbook", "fr"), ("cragbook", "au"), ("knitwit", "fr"), ("knitwit", "au")])

    def test_one_product_in_several_storefronts(self):
        calls = []
        real, aso.check = aso.check, lambda p, country, **k: calls.append((p.name, country))
        try:
            aso_cli.main(["check", "-p", "knitwit", "-c", "fr", "de", "--dry-run"])
        finally:
            aso.check = real
        self.assertEqual(calls, [("knitwit", "fr"), ("knitwit", "de")])

class SummaryTest(TempAso):
    def test_one_line_per_country_with_counts_and_moves(self):
        tsv.write(aso.tsv_path(self.p), aso.FIELDS, [
            rank_row("2026-11-16", "us", "climbing log", api="12"),
            rank_row("2026-11-17", "us", "climbing log", api="9"),
            rank_row("2026-11-17", "us", "hangboard", api="40"),
            rank_row("2026-11-17", "us", "route log"),
            rank_row("2026-11-16", "de", "bouldern lernen", api="20"),
            rank_row("2026-11-17", "de", "bouldern lernen", api="26"),
            rank_row("2026-11-17", "de", "kletter tagebuch", store="3", api="7"),
            rank_row("2026-11-17", "de", "bouldern quiz", store="", api=""),
        ])
        lines = aso.summary(self.p).splitlines()
        us = next(line for line in lines if line.startswith("us"))
        de = next(line for line in lines if line.startswith("de"))
        au = next(line for line in lines if line.startswith("au"))
        self.assertEqual(us.split()[:7], ["us", "2026-11-17", "3", "1", "2", "2", "1"])
        self.assertIn("up 1", us)
        self.assertEqual(de.split()[:7], ["de", "2026-11-17", "3", "1", "2", "2", "1"])
        self.assertIn("down 1", de)
        self.assertIn("no check yet", au)


class ConfigTest(unittest.TestCase):
    def test_countries_are_set_for_cragbook_and_knitwit_only(self):
        found = {p.name: p.get("ASO_COUNTRIES") for p in product.everything() if p.get("ASO_COUNTRIES")}
        self.assertEqual(found, {"cragbook": ["de", "fr", "au"],
                                 "knitwit": ["de", "jp", "fr"]})

    def test_every_tracked_country_has_phrases_to_check(self):
        for p in product.everything():
            for country in aso.countries(p):
                self.assertIn(country, aso.STOREFRONTS, p.name)
                self.assertTrue(aso.keywords(p, country), f"{p.name} {country}")


if __name__ == "__main__":
    unittest.main()
