import sys, tempfile, unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import aso, tsv  # noqa: E402


def row(day, keyword, store, api, country="us", **k):
    return dict.fromkeys(aso.FIELDS, "") | {"date": day, "country": country, "keyword": keyword,
                                            "store_rank": store, "api_rank": api} | k


class Rankings(unittest.TestCase):
    def ranks(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = SimpleNamespace(dir=Path(d), name="x", title="X", get=lambda k, default=None: default)
            (Path(d) / "aso").mkdir()
            tsv.write(aso.tsv_path(p), aso.FIELDS, rows)
            return aso.rankings(p)

    def test_newest_rank_beside_the_one_a_week_before(self):
        [r] = self.ranks([row("2026-11-16", "koi", "9", "30"), row("2026-11-17", "koi", "7", "20"),
                          row("2026-11-23", "koi", "6", "16"),
                          row("2026-11-24", "koi", "5", "15", popularity="72", difficulty="29")])
        self.assertEqual((r["store"], r["api"]), ("5", "15"))
        self.assertEqual((r["was_store"], r["was_api"], r["was_date"]), ("7", "20", "2026-11-17"))
        self.assertEqual((r["pop"], r["diff"]), (72, 29))

    def test_a_missed_day_uses_the_check_before_it(self):
        [r] = self.ranks([row("2026-11-15", "koi", "8", "8"), row("2026-11-24", "koi", "5", "5")])
        self.assertEqual(r["was_date"], "2026-11-15")

    def test_a_phrase_without_a_week_of_checks_has_no_before(self):
        [r] = self.ranks([row("2026-11-22", "koi", "8", "8"), row("2026-11-24", "koi", "5", "5")])
        self.assertEqual((r["was_store"], r["was_api"], r["was_date"]), ("", "", ""))

    def test_a_dropped_phrase_goes_and_a_partial_check_hides_nothing(self):
        out = self.ranks([row("2026-11-10", "old", "1", "1"), row("2026-11-23", "koi", "5", "5"),
                          row("2026-11-24", "pond", "6", "6")])
        self.assertEqual({r["keyword"] for r in out}, {"koi", "pond"})

    def test_storefronts_are_separate(self):
        out = self.ranks([row("2026-11-17", "koi", "1", "1", "de"), row("2026-11-24", "koi", "5", "5")])
        self.assertEqual([(r["country"], r["was_date"]) for r in out if r["country"] == "us"], [("us", "")])

    def test_old_over_200_reads_as_not_found(self):
        [r] = self.ranks([row("2026-11-17", "koi", ">12", ">200"), row("2026-11-24", "koi", ">12", "not found")])
        self.assertEqual((r["api"], r["was_api"]), ("not found", "not found"))

    def test_no_file_is_no_rows(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(aso.rankings(SimpleNamespace(dir=Path(d))), [])


class Search(unittest.TestCase):
    def test_the_request_is_dated_so_each_day_gets_a_fresh_answer(self):
        urls = []
        with mock.patch.object(aso, "fetch", side_effect=lambda u, **k: urls.append(u) or b'{"results": []}'):
            aso.api_search("koi", "us")
        self.assertIn("day=" + date.today().isoformat(), urls[0])

    def test_an_app_the_api_leaves_out_is_not_found(self):
        self.assertEqual(aso.api_rank([{"id": 1}, {"id": 2}], 2), "2")
        self.assertEqual(aso.api_rank([{"id": 1}], 2), "not found")
        self.assertEqual(aso.api_rank(None, 2), "")


if __name__ == "__main__":
    unittest.main()
