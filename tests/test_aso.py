"""The App Store keyword tracker's parts that don't need the network.

    bin/test
"""
import json, plistlib, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import aso, product, tsv  # noqa: E402

US = 1000000002  # Cragbook's APP_STORE_ID in the fixtures


def api(*apps):
    return json.dumps({"resultCount": len(apps), "results": [
        {"trackId": i, "trackName": n, "userRatingCount": r, "price": 1.99} for i, n, r in apps]}).encode()


# The shape of apps.apple.com's search page: each result links
# /<country>/app/<slug>/id<N>, sometimes more than once.
STORE = """<a href="https://apps.apple.com/us/app/example-crag-climbing-tracker/id1000000201">x</a>
<a href="https://apps.apple.com/us/app/example-crag-climbing-tracker/id1000000201">View</a>
<a href="/us/app/cragbook-climbing-log/id1000000002">y</a>
<a href="/us/app/sample-sends-boulder-journal/id1000000202">z</a>"""


class SourcesTest(unittest.TestCase):
    def test_api_results_keep_order_and_ratings(self):
        rows = aso.api_results(api((1, "A", 10), (2, "B", 0)))
        self.assertEqual([r["id"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["ratings"], 10)

    def test_store_results_dedupe_in_page_order(self):
        rows = aso.store_results(STORE)
        self.assertEqual([r["id"] for r in rows], [1000000201, US, 1000000202])
        self.assertEqual(rows[1]["name"], "cragbook climbing log")

    def test_hint_terms(self):
        data = plistlib.dumps({"title": "Suggestions", "hints": [{"term": "Climbing Log", "url": "u"}]})
        self.assertEqual(aso.hint_terms(data), ["climbing log"])


class ScoresTest(unittest.TestCase):
    def test_typed_letters_stops_at_the_first_suggestion(self):
        asked = []

        def fake(prefix, country, cache):
            asked.append(prefix)
            return ["climbing log"] if len(prefix) >= 4 else ["clim"]

        real, aso.hints = aso.hints, fake
        try:
            self.assertEqual(aso.typed_letters("Climbing Log", "us", {}), 4)
        finally:
            aso.hints = real
        self.assertEqual(asked[0], "climbing log")
        self.assertLessEqual(len(asked), 5)

    def test_a_phrase_never_suggested_costs_one_request(self):
        asked = []

        def fake(prefix, country, cache):
            asked.append(prefix)
            return ["clim"]

        real, aso.hints = aso.hints, fake
        try:
            self.assertIsNone(aso.typed_letters("climbing log", "us", {}))
        finally:
            aso.hints = real
        self.assertEqual(asked, ["climbing log"])

    def test_popularity_falls_with_letters_typed(self):
        self.assertEqual(aso.popularity(2), 100)
        self.assertGreater(aso.popularity(3), aso.popularity(8))
        self.assertEqual(aso.popularity(None), 0)
        self.assertGreaterEqual(aso.popularity(60), 1)

    def test_difficulty_from_the_top_ten_median(self):
        results = [{"ratings": n} for n in [1000] * 10 + [0] * 5]
        self.assertEqual(aso.difficulty(results), (75, 1000))
        self.assertEqual(aso.difficulty([]), (0, 0))
        self.assertEqual(aso.difficulty([{"ratings": 10 ** 6}])[0], 100)

    def test_rank(self):
        rows = [{"id": 1}, {"id": US}]
        self.assertEqual(aso.rank(rows, US), "2")
        self.assertEqual(aso.rank([{"id": 1}], US, 12), ">12")
        self.assertEqual(aso.rank(None, US), "")

    def test_ahead_lists_tracked_apps_above_us_only(self):
        rows = [{"id": 1}, {"id": 5}, {"id": 2}, {"id": US}, {"id": 3}]
        self.assertEqual(aso.ahead(rows, US, {"One": 1, "Two": 2, "Three": 3}), "One, Two")


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("cragbook")
        self.p.dir = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def row(self, day, keyword, api_rank):
        return dict.fromkeys(aso.FIELDS, "") | {"date": day, "country": "us", "keyword": keyword, "api_rank": api_rank}

    def test_latest_takes_the_newest_row_per_keyword(self):
        path = aso.tsv_path(self.p)
        path.parent.mkdir()
        tsv.write(path, aso.FIELDS, [self.row("2026-10-26", "bouldering", "70"), self.row("2026-10-27", "bouldering", "68"),
                                     self.row("2026-10-27", "hangboard", ">200")])
        self.assertEqual(aso.latest(self.p)["bouldering"]["api_rank"], "68")
        self.assertEqual(aso.latest(self.p, before="2026-10-27"), {"bouldering": self.row("2026-10-26", "bouldering", "70")})
        self.assertEqual(aso.latest(self.p, country="gb"), {})

    def test_table_brackets_only_ranks_that_moved(self):
        now = [self.row("2026-10-27", "bouldering", "68") | {"store_rank": ">12"}]
        was = {"bouldering": self.row("2026-10-26", "bouldering", "70") | {"store_rank": ">12"}}
        line = aso.table(self.p, now, was).splitlines()[-1]
        self.assertIn("68 (70)", line)
        self.assertNotIn("(>12)", line)


class ProductsTest(unittest.TestCase):
    def test_tracked_products_have_an_id_and_unique_keywords(self):
        for p in product.everything():
            keywords = p.get("ASO_KEYWORDS")
            if keywords is None:
                continue
            self.assertIsInstance(p.need("APP_STORE_ID"), int, p.name)
            self.assertEqual(len(keywords), len({k.lower() for k in keywords}), p.name)


class DailyTest(unittest.TestCase):
    def test_plist_runs_check_all_from_the_repo(self):
        d = plistlib.loads(aso.plist(9, 15, Path("/repo"), "/py", Path("/log")))
        self.assertEqual(d["ProgramArguments"], ["/py", "-m", "leadkit.aso_cli", "check", "--all"])
        self.assertEqual(d["EnvironmentVariables"]["PYTHONPATH"], "/repo")
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 9, "Minute": 15})



class HintCacheTest(unittest.TestCase):
    def test_a_failed_lookup_is_not_cached_as_unsuggested(self):
        replies = [None, plistlib.dumps({"hints": [{"term": "Klettern"}]})]
        real, aso.fetch = aso.fetch, lambda *a, **k: replies.pop(0)
        try:
            cache = {}
            self.assertEqual(aso.hints("kl", "de", cache), [])
            self.assertNotIn("kl", cache)
            self.assertEqual(aso.hints("kl", "de", cache), ["klettern"])
        finally:
            aso.fetch = real


if __name__ == "__main__":
    unittest.main()
