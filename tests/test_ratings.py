import json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import ratings  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def run_with(code, out="", err=""):
    return lambda cmd, **k: SimpleNamespace(returncode=code, stdout=out, stderr=err)


class Rating(unittest.TestCase):
    def test_average_and_count(self):
        r = ratings.rating("1", run_with(0, json.dumps({"averageRating": 4.857, "totalCount": 7})))
        self.assertEqual(r, {"avg": 4.86, "count": 7})

    def test_no_ratings_anywhere_is_zero(self):
        r = ratings.rating("1", run_with(1, err="Error: reviews ratings: app not found in any country: 1"))
        self.assertEqual(r, {"avg": 0, "count": 0})

    def test_other_errors_raise(self):
        with self.assertRaises(RuntimeError):
            ratings.rating("1", run_with(1, err="Error: 401"))


class Fetch(unittest.TestCase):
    def test_a_failing_app_keeps_its_saved_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ratings.json"
            ratings.fetch([("1", "Knitwit: A")], path, lambda i: {"avg": 5, "count": 6}, now=NOW)

            def broken(i):
                raise RuntimeError("timeout")
            out = ratings.fetch([("1", "Knitwit: A")], path, broken, now=NOW)
            self.assertEqual(out["apps"]["1"]["count"], 6)
            self.assertEqual(len(out["errors"]), 1)
            self.assertEqual(ratings.load(path)["apps"]["1"]["avg"], 5)

    def test_a_drop_to_zero_keeps_the_saved_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ratings.json"
            ratings.fetch([("1", "Cragbook: A")], path, lambda i: {"avg": 4.5, "count": 8}, now=NOW)
            out = ratings.fetch([("1", "Cragbook: A")], path, lambda i: {"avg": 0, "count": 0}, now=NOW)
            self.assertEqual(out["apps"]["1"]["count"], 8)


    def test_play_ratings_are_kept_apart_and_named_after_the_app(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ratings.json"
            out = ratings.fetch([("1", "Knitwit: Row Counter")], path, lambda i: {"avg": 5, "count": 6}, now=NOW,
                                play=lambda: {"com.example.knitwit": {"avg": 4.5, "count": 2}, "com.example.zed": {"avg": 3, "count": 1}})
            self.assertEqual(out["apps"]["1"]["count"], 6)
            self.assertEqual(out["play"]["com.example.knitwit"], {"title": "Knitwit: Row Counter", "avg": 4.5, "count": 2})
            self.assertEqual(out["play"]["com.example.zed"]["title"], "Zed", "an app with no App Store twin is named from its package")

    def test_a_play_failure_keeps_the_saved_play_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ratings.json"
            ratings.fetch([("1", "Knitwit: A")], path, lambda i: {"avg": 5, "count": 6}, now=NOW,
                          play=lambda: {"com.example.knitwit": {"avg": 5, "count": 3}})

            def broken():
                raise RuntimeError("bucket said no")
            out = ratings.fetch([("1", "Knitwit: A")], path, lambda i: {"avg": 5, "count": 6}, now=NOW, play=broken)
            self.assertEqual(out["play"]["com.example.knitwit"]["count"], 3)
            self.assertTrue(any("Play" in e for e in out["errors"]))

    def test_play_ratings_parse_the_command_output(self):
        got = ratings.play_ratings(run_with(0, json.dumps({"dev.x": {"avg": 5.0, "count": 1}})))
        self.assertEqual(got, {"dev.x": {"avg": 5.0, "count": 1}})
        with self.assertRaises(RuntimeError):
            ratings.play_ratings(run_with(1, err="HTTP 403"))


if __name__ == "__main__":
    unittest.main()
