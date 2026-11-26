import json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import eastern  # noqa: E402


def sold(app, date, units=1, sales=2.0, proceeds=1.7, store="iOS"):
    return {"date": date, "app": app, "store": store, "units": str(units),
            "proceeds": f"{proceeds:.2f}", "sales": f"{sales:.2f}"}


def hour(app, at, region="-100001", units=1, sales=2.0, proceeds=1.7, store="iOS", country="143441"):
    return {"at": at, "app": app, "store": store, "country": country, "region": region,
            "units": units, "sales": sales, "proceeds": proceeds}


def units(rows):
    return {(r["date"], r["store"]): int(r["units"]) for r in rows if int(r["units"])}


class StoreDayTest(unittest.TestCase):
    """Worked out 2026-11-25: 38 of 38 iOS units Nov 20-24 fit these report days."""

    def test_report_days_seen(self):
        for at, region, country, day in [
                ("2026-11-24T06:00:00Z", "-100001", "143441", "2026-11-23"),  # US, Pacific
                ("2026-11-20T05:00:00Z", "-100003", "143443", "2026-11-20"),  # Germany, 9 p.m. PT on the 19th
                ("2026-11-19T16:00:00Z", "-100004", "143462", "2026-11-20"),  # Japan
                ("2026-11-20T15:00:00Z", "-100004", "143473", "2026-11-21"),  # Malaysia is on Japan's day
                ("2026-11-24T15:00:00Z", "-100004", "143474", "2026-11-25")]:  # the Philippines too
            self.assertEqual(eastern.store_day(hour("A", at, region, country=country)), day, at)

    def test_play_days_are_utc(self):
        self.assertEqual(eastern.store_day(hour("A", "2026-11-22T01:00:00Z", store="Play")), "2026-11-22")

    def test_eastern_day_follows_daylight_saving(self):
        self.assertEqual(eastern.eastern_day("2026-11-22T04:30:00Z"), "2026-11-21")
        self.assertEqual(eastern.eastern_day("2026-10-22T04:30:00Z"), "2026-10-22")


class RowsTest(unittest.TestCase):
    def test_a_sale_moves_and_keeps_the_reports_money(self):
        out = eastern.rows([sold("A", "2026-11-23", sales=1.99, proceeds=1.69)],
                           [hour("A", "2026-11-24T06:00:00Z", sales=2.5, proceeds=2)], "2026-11-24")
        self.assertEqual([(r["date"], r["units"], r["sales"], r["proceeds"]) for r in out],
                         [("2026-11-24", 1, 1.99, 1.69)])

    def test_days_without_hours_stay(self):
        old = [sold("A", "2026-11-01", units=3)]
        self.assertEqual(units(eastern.rows(old, [], "2026-11-24")), {("2026-11-01", "iOS"): 3})

    def test_a_partly_known_day_moves_only_what_is_known(self):
        out = eastern.rows([sold("A", "2026-11-23", units=3, sales=6, proceeds=5.1)],
                           [hour("A", "2026-11-24T06:00:00Z")], "2026-11-24")
        self.assertEqual(units(out), {("2026-11-23", "iOS"): 2, ("2026-11-24", "iOS"): 1})
        self.assertAlmostEqual(sum(r["sales"] for r in out), 6)

    def test_more_hours_than_the_report_changes_nothing(self):
        out = eastern.rows([sold("A", "2026-11-23")],
                           [hour("A", "2026-11-24T06:00:00Z"), hour("A", "2026-11-23T20:00:00Z")], "2026-11-24")
        self.assertEqual(units(out), {("2026-11-23", "iOS"): 1})

    def test_sales_the_report_has_not_reached_come_from_the_hours(self):
        out = eastern.rows([sold("A", "2026-11-23")], [hour("A", "2026-11-24T20:00:00Z")], "2026-11-24")
        self.assertEqual(units(out), {("2026-11-23", "iOS"): 1, ("2026-11-24", "iOS"): 1})

    def test_an_unfinished_eastern_day_is_left_out(self):
        out = eastern.rows([sold("A", "2026-11-23")], [hour("A", "2026-11-25T20:00:00Z")], "2026-11-24")
        self.assertEqual(units(out), {("2026-11-23", "iOS"): 1})

    def test_play_evening_sale_moves_back_a_day(self):
        out = eastern.rows([sold("A", "2026-11-22", store="Play")],
                           [hour("A", "2026-11-22T01:00:00Z", store="Play")], "2026-11-24")
        self.assertEqual(units(out), {("2026-11-21", "Play"): 1})


class ThroughTest(unittest.TestCase):
    def test_yesterday_once_its_hours_are_in(self):
        self.assertEqual(eastern.through([], "2026-11-25T08:00:00Z"), "2026-11-24")
        self.assertEqual(eastern.through([], "2026-11-25T06:00:00Z"), "2026-11-23", "Trends runs up to 2 hours behind")

    def test_a_signed_out_stamp_falls_back_to_the_reports(self):
        self.assertEqual(eastern.through([sold("A", "2026-11-24")], "2026-11-20T08:00:00Z"), "2026-11-24")


class SaveTest(unittest.TestCase):
    def test_merge_replaces_recent_keeps_expired(self):
        old = [hour("A", "2026-11-10T06:00:00Z"), hour("A", "2026-11-24T06:00:00Z")]
        got = eastern.merge(old, [hour("A", "2026-11-24T07:00:00Z")], "iOS", "2026-11-21T00:00:00Z")
        self.assertEqual([r["at"] for r in got], ["2026-11-10T06:00:00Z", "2026-11-24T07:00:00Z"])

    def test_merge_updates_an_older_hour_in_place(self):
        got = eastern.merge([hour("A", "2026-11-10T06:00:00Z")], [hour("A", "2026-11-10T06:00:00Z", units=2)], "iOS", "2026-11-21T00:00:00Z")
        self.assertEqual([r["units"] for r in got], [2])

    def test_an_empty_answer_deletes_nothing(self):
        old = [hour("A", "2026-11-24T06:00:00Z")]
        self.assertEqual(eastern.merge(old, [], "iOS", "2026-11-21T00:00:00Z"), old)

    def test_two_play_orders_in_one_second_both_count(self):
        o = hour("A", "2026-11-24T06:00:00Z", store="Play")
        self.assertEqual(len(eastern.merge([], [o, dict(o)], "Play", "2026-11-21T00:00:00Z")), 2)

    def test_a_store_failing_keeps_its_rows_and_reports_why(self):
        def broken(*a):
            raise RuntimeError("signed out")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hours.json"
            eastern.write(path, {"fetched": "2026-11-20T08:00:00Z", "rows": [hour("A", "2026-11-19T06:00:00Z")]})
            lines = eastern.sync(["A"], path, datetime(2026, 11, 25, 8, tzinfo=timezone.utc), ios=broken,
                                 play=lambda *a: [hour("A", "2026-11-24T06:00:00Z", store="Play")])
            got = eastern.load(path)
            self.assertEqual((len(got["rows"]), got["fetched"]), (2, "2026-11-20T08:00:00Z"))
            self.assertIn("signed out", " ".join(lines))

    def test_trends_answer_parses(self):
        result = [{"metadata": [{"dimension": "content", "title": "Alpha: Notes", "key": 1},
                                {"dimension": "piano_location", "key": 143443, "parentKey": "-100003"}],
                   "data": [{"hour": "2026-11-20T05:00:00Z", "units_utc": 1, "total_tax_usd_utc": 1.1, "Royalty_utc": .79}]}]
        self.assertEqual(eastern.parse(result, ["Alpha"]), [hour("Alpha", "2026-11-20T05:00:00Z", "-100003", sales=1.1, proceeds=.79, country="143443")])


if __name__ == "__main__":
    unittest.main()
