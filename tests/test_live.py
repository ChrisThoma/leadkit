import io, json, sys, time, unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadkit import analytics, live  # noqa: E402

NOW = datetime(2026, 11, 21, 19, 25, tzinfo=timezone.utc)


def group(app_id, title, rows):
    return {"metadata": [{"key": int(app_id), "title": title, "supportedPlatformName": "iOS"}],
            "data": [{"units_utc": u, "total_tax_usd_utc": s, "hour": h} for h, u, s in rows]}


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(replies):
    """Answers each POST with the next reply; keeps the bodies it was sent."""
    sent = []

    def opener(req, timeout=None):
        sent.append(json.loads(req.data))
        return Reply(replies.pop(0).encode())
    opener.sent = sent
    return opener


class LiveTest(unittest.TestCase):
    """The only near-live sales are on App Store Connect's Trends page, whose endpoint
    takes this body (found by testing it against the page's own session)."""

    def test_window_is_the_last_24_whole_hours(self):
        self.assertEqual(live.window(NOW), ("2026-11-20T19:00:00.000Z", "2026-11-21T18:00:00.000Z"))

    def test_body_asks_for_units_and_sales_by_app(self):
        b = live.body("s", "e")
        self.assertEqual(b["interval"], {"key": "hour", "startDate": "s", "endDate": "e"})
        self.assertEqual([m["key"] for m in b["measures"]], ["units_utc", "total_tax_usd_utc"])
        self.assertEqual(b["group"], ["content"], "group as objects gets 'Invalid request payload'")

    def test_fetch_joins_the_day_before_by_app(self):
        now = json.dumps({"status": "success", "result": [
            group("1", "Cragbook", [("2026-11-21T03:00:00Z", 2, 9.98)]),
            group("2", "Knitwit", [("2026-11-21T04:00:00Z", 1, 2.99)])]})
        before = json.dumps({"status": "success", "result": [
            group("2", "Knitwit", [("2026-11-20T04:00:00Z", 3, 8.97)]),
            group("3", "Paper Kite", [("2026-11-20T05:00:00Z", 1, 2.99)])]})
        op = opener_for([now, before])
        d = live.fetch(NOW, cookie="c=1", opener=op, play=({"updated": "", "orders": []}, ""))
        by = {a["title"]: a for a in d["apps"]}
        self.assertEqual(by["Cragbook"]["hours"]["2026-11-21T03:00:00Z"], {"units": 2, "sales": 9.98})
        self.assertEqual((by["Cragbook"]["prev_units"], by["Knitwit"]["prev_units"]), (0, 3))
        self.assertEqual((by["Paper Kite"]["hours"], by["Paper Kite"]["prev_units"]), ({}, 1),
                         "an app that sold only the day before still shows, at 0")
        self.assertEqual(op.sent[1]["interval"]["startDate"], "2026-11-19T19:00:00.000Z")

    def test_play_orders_join_their_app_by_hour(self):
        now = json.dumps({"status": "success", "result": [group("2", "Knitwit: Row Counter", [("2026-11-21T04:00:00Z", 1, 2.99)])]})
        before = json.dumps({"status": "success", "result": []})
        orders = [{"at": "2026-11-20T04:10:00Z", "title": "Knitwit: contador de vueltas", "kind": "app", "sales": 0.85},
                  {"at": "2026-11-21T04:30:00Z", "title": "Knitwit: compteur de rangs", "kind": "app", "sales": 1.10},
                  {"at": "2026-11-21T09:02:00Z", "title": "Cragbook: Climbing Log", "kind": "app", "sales": 2.25},
                  {"at": "2026-11-18T09:00:00Z", "title": "Cragbook: Climbing Log", "kind": "app", "sales": 2.25}]
        d = live.fetch(NOW, cookie="c=1", opener=opener_for([now, before]), play=({"updated": "2026-11-21T19:28:26Z", "orders": orders}, ""), names=["Knitwit", "Cragbook"])
        by = {a["title"].split(":")[0]: a for a in d["apps"]}
        self.assertEqual(by["Knitwit"]["hours"]["2026-11-21T04:00:00Z"], {"units": 2, "sales": 4.09, "play": 1},
                         "a localized Play title lands on the iOS app's row, in the same hour")
        self.assertEqual((by["Knitwit"]["play_units"], by["Knitwit"]["prev_units"], by["Knitwit"]["prev_play_units"]), (1, 1, 1))
        self.assertEqual((by["Cragbook"]["platform"], by["Cragbook"]["play_units"], by["Cragbook"]["prev_units"]), ("Android", 1, 0),
                         "a Play-only app gets a row; an order older than 48 hours is left out")
        self.assertEqual(d["play_updated"], "2026-11-21T19:28:26Z")

    def test_play_sales_is_found_off_the_path(self):
        from unittest import mock
        from leadkit import product
        with mock.patch.dict("os.environ", {"PATH": "/usr/bin:/bin"}):
            self.assertEqual(live.play_sales(), str(product.HOME / "bin" / "play-sales"),
                             "a server started without the tools on PATH still reads Play")

    def test_play_failing_leaves_apple_alone(self):
        now = json.dumps({"status": "success", "result": [group("2", "Knitwit", [("2026-11-21T04:00:00Z", 1, 2.99)])]})
        d = live.fetch(NOW, cookie="c=1", opener=opener_for([now, json.dumps({"status": "success", "result": []})]),
                       play=(None, "Missing PLAY_BUCKET"))
        self.assertEqual((d["apps"][0]["hours"]["2026-11-21T04:00:00Z"]["units"], d["play_error"]), (1, "Missing PLAY_BUCKET"))

    def test_a_sign_in_page_means_signed_out(self):
        with self.assertRaises(live.SignedOut):
            live.fetch(NOW, cookie="c=1", play=({"updated": "", "orders": []}, ""), opener=opener_for(["<!DOCTYPE html><html>sign in</html>"]))

    def test_an_error_reply_is_not_mistaken_for_no_sales(self):
        bad = json.dumps({"status": "error", "error": {"code": "GSF01004"}})
        with self.assertRaises(RuntimeError):
            live.fetch(NOW, cookie="c=1", play=({"updated": "", "orders": []}, ""), opener=opener_for([bad]))


class JobTest(unittest.TestCase):
    """The Sync button: one run at a time, its lines and errors kept for the page."""

    def wait(self, job):
        for _ in range(100):
            if not job.running:
                return
            time.sleep(0.02)

    def test_one_at_a_time_and_lines_kept(self):
        def work(log):
            log("first")
            time.sleep(0.1)
            log("second")
        job = analytics.Job(work)
        self.assertTrue(job.start())
        self.assertFalse(job.start(), "a second press while running doesn't start another")
        self.wait(job)
        st = job.state()
        self.assertEqual((st["running"], st["lines"], st["error"]), (False, ["first", "second"], None))
        self.assertTrue(st["finished"])

    def test_a_failure_is_reported(self):
        def work(log):
            raise RuntimeError("asc said no")
        job = analytics.Job(work)
        job.start()
        self.wait(job)
        self.assertEqual(job.state()["error"], "asc said no")


class LastSyncTest(unittest.TestCase):
    """The dashboard's "Last synced": a finished sync leaves its time; none yet is empty."""

    def test_round_trip_and_missing(self):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "last-sync.json"
            self.assertEqual(analytics.last_sync(path), "")
            analytics.mark_synced(path, datetime(2026, 11, 22, 8, 2, tzinfo=timezone.utc))
            self.assertEqual(analytics.last_sync(path), "2026-11-22T08:02:00Z")
            path.write_text("not json")
            self.assertEqual(analytics.last_sync(path), "", "a broken file reads as never synced")

    def test_fallback_takes_the_newer_of_commit_and_downloads(self):
        """With no stamp yet, a Sync-button run (files, no commit) beats an older 3 a.m. commit."""
        import os, tempfile
        from datetime import datetime, timezone
        from leadkit import dashboard
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            (raw / "1" / "downloads").mkdir(parents=True)
            f = raw / "1" / "downloads" / "ongoing-2026-11-22.tsv.gz"
            f.write_text("x")
            t = datetime(2026, 11, 22, 18, 23, 34, tzinfo=timezone.utc).timestamp()  # 1:23 PM ET
            os.utime(f, (t, t))
            stamp = Path(d) / "none.json"
            got = dashboard.last_synced(stamp=stamp, raw=raw, commit=lambda: "2026-11-22T03:03:26-05:00")
            self.assertEqual(got, "2026-11-22T18:23:34Z")
            got = dashboard.last_synced(stamp=stamp, raw=raw, commit=lambda: "2026-11-22T14:00:00-05:00")
            self.assertEqual(got, "2026-11-22T19:00:00Z", "a later commit still wins")
            analytics.mark_synced(stamp, datetime(2026, 11, 23, 8, 2, tzinfo=timezone.utc))
            self.assertEqual(dashboard.last_synced(stamp=stamp, raw=raw, commit=lambda: ""), "2026-11-23T08:02:00Z", "a newer stamp wins")
            self.assertEqual(dashboard.last_synced(stamp=Path(d) / "x.json", raw=Path(d) / "nope", commit=lambda: ""), "")


if __name__ == "__main__":
    unittest.main()
