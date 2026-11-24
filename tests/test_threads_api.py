"""The Threads API features: leads keep the post id, replies and deletes go
through the API and update the TSV, mentions become leads, insights are logged."""
import sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import threads, threadsapi, tsv  # noqa: E402
from leadkit.threadsapi import ApiError  # noqa: E402
from helpers import TempProduct, ago  # noqa: E402

OLD = ["found", "posted", "priority", "author", "url", "engagement", "pitch", "reply", "notes", "status"]


def post(pid, user, text="how do I keep track of my rows?"):
    return {"id": pid, "username": user, "text": text, "timestamp": "2026-10-30T10:00:00+0000",
            "permalink": f"https://www.threads.com/@{user}/post/P{pid}"}


class FakeApi:
    """Stands in for threadsapi.call: records each request, answers from a table."""
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, path, tok, params=None, method="GET"):
        self.calls.append((method, path, dict(params or {})))
        if (method, path) in self.answers:
            return self.answers[(method, path)]
        if method == "POST" and path == "me/threads":
            return {"id": "C1"}
        if method == "POST" and path == "me/threads_publish":
            return {"id": "R1"}
        if path == "R1":
            return {"permalink": "https://www.threads.com/@mythreadshandle/post/R1"}
        return {"data": [], "success": True}


class LeadIdTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()

    def tearDown(self):
        self.t.close()

    def test_added_lead_keeps_the_post_id_even_in_an_old_file(self):
        self.t.write("Threads", [{"url": "https://www.threads.com/@x/post/OLD", "status": "new"}], fields=OLD)
        row = threads.add_lead(self.t.p, post("42", "someone"), "search row counter")
        self.assertEqual(row["id"], "42")
        fields, rows = tsv.read(self.t.p.threads_tsv)
        self.assertIn("id", fields)
        self.assertEqual([r["id"] for r in rows], ["", "42"])

    def test_own_and_seen_posts_are_not_added(self):
        self.assertIsNotNone(threads.add_lead(self.t.p, post("1", "someone"), "x"))
        self.assertIsNone(threads.add_lead(self.t.p, post("1", "someone"), "x"))
        self.assertIsNone(threads.add_lead(self.t.p, post("2", "mythreadshandle"), "x"))

    def test_mentions_become_new_leads(self):
        api = FakeApi({("GET", "me/mentions"): {"data": [post("7", "fan"), post("8", "mythreadshandle")]}})
        with mock.patch.object(threadsapi, "call", api):
            rows = threads.add_mentions(self.t.p, "tok")
        self.assertEqual([r["id"] for r in rows], ["7"])
        self.assertEqual(self.t.read("Threads")[0]["status"], "new")


class ReplyTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        fields = OLD + ["id"]
        self.t.write("Threads", [
            {"url": "https://www.threads.com/@a/post/PA", "id": "100", "reply": '"Try a stitch marker every ten rows."',
             "status": "draft", "posted": ago(0)},
            {"url": "https://www.threads.com/@b/post/PB", "reply": "No id here.", "status": "draft"},
            {"url": "https://www.threads.com/@c/post/PC", "id": "300", "reply": "x" * 501, "status": "draft"},
        ], fields=fields)

    def tearDown(self):
        self.t.close()

    def test_reply_publishes_under_the_post_and_marks_it_posted(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            threads.reply_to_lead(self.t.p, "https://www.threads.com/@a/post/PA", "tok")
        container = api.calls[0]
        self.assertEqual(container[:2], ("POST", "me/threads"))
        self.assertEqual(container[2]["reply_to_id"], "100")
        self.assertEqual(container[2]["text"], "Try a stitch marker every ten rows.")  # quotes stripped
        a = self.t.read("Threads")[0]
        self.assertEqual(a["status"], "posted")
        self.assertEqual(a["reply_id"], "R1")
        self.assertIn("Reply: https://www.threads.com/@mythreadshandle/post/R1", a["notes"])

    def test_refuses_without_an_id_or_over_the_limit(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            with self.assertRaises(ValueError):
                threads.reply_to_lead(self.t.p, "https://www.threads.com/@b/post/PB", "tok")
            with self.assertRaises(ValueError):
                threads.reply_to_lead(self.t.p, "https://www.threads.com/@c/post/PC", "tok")
        self.assertEqual(api.calls, [])

    def test_delete_removes_our_reply_and_records_it(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            threads.reply_to_lead(self.t.p, "https://www.threads.com/@a/post/PA", "tok")
            threads.delete_reply(self.t.p, "https://www.threads.com/@a/post/PA", "tok")
        self.assertEqual(api.calls[-1][:2], ("DELETE", "R1"))
        a = self.t.read("Threads")[0]
        self.assertEqual(a["status"], "deleted")
        self.assertEqual(a["reply_id"], "")

    def test_delete_refuses_a_row_without_our_reply(self):
        with mock.patch.object(threadsapi, "call", FakeApi()):
            with self.assertRaises(ValueError):
                threads.delete_reply(self.t.p, "https://www.threads.com/@b/post/PB", "tok")


class InsightsTest(unittest.TestCase):
    def test_one_row_per_post_per_day(self):
        t = TempProduct()
        path = t.tmp / "threads-insights.tsv"
        api = FakeApi({
            ("GET", "me/threads"): {"data": [post("9", "mythreadshandle", "new post")]},
            ("GET", "9/insights"): {"data": [{"name": "views", "values": [{"value": 79}]},
                                             {"name": "likes", "values": [{"value": 3}]}]},
        })
        with mock.patch.object(threadsapi, "call", api):
            threads.log_insights("tok", path)
            threads.log_insights("tok", path)
        rows = tsv.read(path)[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["views"], rows[0]["likes"]), ("79", "3"))
        t.close()

    def test_rows_say_when_the_post_went_up_and_skip_reposts(self):
        # A day's views only compare with an older post's at the same age, so each row
        # keeps the post's own time. Reposts come back with no text and no insights.
        t = TempProduct()
        path = t.tmp / "threads-insights.tsv"
        api = FakeApi({
            ("GET", "me/threads"): {"data": [post("9", "mythreadshandle", "new post"),
                                             {"id": "8", "timestamp": "2026-10-29T02:01:00+0000"}]},
            ("GET", "9/insights"): {"data": [{"name": "views", "values": [{"value": 4}]}]},
        })
        with mock.patch.object(threadsapi, "call", api):
            rows = threads.log_insights("tok", path)
        self.assertEqual([r["posted"] for r in rows], ["2026-10-30 10:00"])
        self.assertNotIn(("GET", "8/insights", {"metric": ",".join(threadsapi.METRICS), "access_token": "tok"}),
                         api.calls)
        t.close()


def own_reply(n, ts="2026-11-10T10:00:00+0000", text="a reply"):
    return {"id": f"r{n}", "text": text, "timestamp": ts,
            "permalink": f"https://www.threads.com/@mythreadshandle/post/S{n}"}


def views(n):
    return {"data": [{"name": "views", "values": [{"value": n}]}, {"name": "likes", "values": [{"value": 1}]}]}


class OwnRepliesTest(unittest.TestCase):
    def test_follows_after_cursors_until_a_page_has_none(self):
        pages = {None: {"data": [own_reply(1), own_reply(2)], "paging": {"cursors": {"after": "C1"}}},
                 "C1": {"data": [own_reply(3)], "paging": {"cursors": {"after": "C2"}}},
                 "C2": {"data": [own_reply(4)], "paging": {"cursors": {"before": "B"}}}}
        seen = []

        def call(path, tok, params=None, method="GET"):
            seen.append((path, dict(params)))
            return pages[(params or {}).get("after")]
        with mock.patch.object(threadsapi, "call", call):
            got = threadsapi.own_replies("tok")
        self.assertEqual([r["id"] for r in got], ["r1", "r2", "r3", "r4"])
        self.assertEqual([s[0] for s in seen], ["me/replies"] * 3)
        self.assertEqual(seen[0][1], {"fields": "id,text,permalink,timestamp", "limit": 100})
        self.assertEqual([s[1].get("after") for s in seen], [None, "C1", "C2"])

    def test_a_single_page(self):
        with mock.patch.object(threadsapi, "call", lambda *a, **k: {"data": [own_reply(1)]}):
            self.assertEqual(len(threadsapi.own_replies("tok")), 1)


class ReplyInsightsTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.path = self.t.tmp / "threads-replies.tsv"
        self.today = threads.datetime.now(threads.timezone.utc)

    def tearDown(self):
        self.t.close()

    def ts(self, days):
        return (self.today - threads.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+0000")

    def run_log(self, replies, metrics, **kw):
        asked = []

        def insights(tok, rid):
            asked.append(rid)
            if isinstance(metrics[rid], Exception):
                raise metrics[rid]
            return metrics[rid]
        with mock.patch.object(threadsapi, "own_replies", lambda tok, limit=100: replies), \
             mock.patch.object(threadsapi, "insights", insights):
            rows = threads.log_reply_insights("tok", self.path, **kw)
        return rows, asked

    def test_first_run_backfills_everything_newest_first(self):
        replies = [own_reply(1, self.ts(40), "old\ttab"), own_reply(2, self.ts(1), "new\nline"),
                   own_reply(3, self.ts(20))]
        rows, asked = self.run_log(replies, {f"r{i}": {"views": i * 10, "likes": 1} for i in (1, 2, 3)})
        self.assertEqual(sorted(asked), ["r1", "r2", "r3"])
        fields, got = tsv.read(self.path)
        self.assertEqual(fields, threads.REPLIES_FIELDS)
        self.assertEqual([r["id"] for r in got], ["r2", "r3", "r1"])
        new = got[0]
        self.assertEqual((new["views"], new["likes"], new["text"]), ("20", "1", "new line"))
        self.assertEqual(new["posted"], self.ts(1)[:16].replace("T", " "))
        self.assertEqual(new["read"], self.today.date().isoformat())
        self.assertEqual(got[2]["text"], "old tab")
        self.assertEqual(len(rows), 3)

    def test_later_runs_only_ask_for_new_and_fresh_replies(self):
        old, fresh = own_reply(1, self.ts(40)), own_reply(2, self.ts(3))
        self.run_log([fresh, old], {"r1": {"views": 5}, "r2": {"views": 1}})
        new = own_reply(3, self.ts(0))
        rows, asked = self.run_log([new, fresh, old], {"r3": {"views": 2}, "r2": {"views": 9}})
        self.assertEqual(sorted(asked), ["r2", "r3"])  # the 40-day-old reply is left alone
        got = {r["id"]: r for r in tsv.read(self.path)[1]}
        self.assertEqual((got["r1"]["views"], got["r2"]["views"], got["r3"]["views"]), ("5", "9", "2"))
        self.assertEqual(len(got), 3)  # upsert, no duplicate
        self.assertEqual(sorted(r["id"] for r in rows), ["r2", "r3"])

    def test_fresh_days_is_adjustable(self):
        self.run_log([own_reply(1, self.ts(3))], {"r1": {"views": 1}})
        _, asked = self.run_log([own_reply(1, self.ts(3))], {"r1": {"views": 2}}, fresh_days=2)
        self.assertEqual(asked, [])

    def test_an_api_error_on_one_reply_leaves_it_out_and_keeps_going(self):
        replies = [own_reply(1, self.ts(1)), own_reply(2, self.ts(2))]
        rows, _ = self.run_log(replies, {"r1": ApiError(400, "gone"), "r2": {"views": 4}})
        self.assertEqual([r["id"] for r in rows], ["r2"])
        self.assertEqual([r["id"] for r in tsv.read(self.path)[1]], ["r2"])

    def test_an_error_keeps_the_old_row(self):
        self.run_log([own_reply(1, self.ts(1))], {"r1": {"views": 4}})
        rows, _ = self.run_log([own_reply(1, self.ts(1))], {"r1": ApiError(500, "down")})
        self.assertEqual(rows, [])
        self.assertEqual([(r["id"], r["views"]) for r in tsv.read(self.path)[1]], [("r1", "4")])

    def test_a_reply_without_a_link_is_skipped(self):
        bad = own_reply(1, self.ts(1)) | {"permalink": ""}
        rows, asked = self.run_log([bad], {})
        self.assertEqual((rows, asked), ([], []))


class InsightsJobTest(unittest.TestCase):
    def test_plist_runs_the_scheduled_log_from_this_checkout(self):
        import plistlib
        job = plistlib.loads(threads.insights_plist(9, 20, Path("/repo"), "/py/python3", Path("/log")))
        self.assertEqual(job["Label"], threads.INSIGHTS_LABEL)
        self.assertEqual(job["ProgramArguments"], ["/py/python3", "-m", "leadkit.cli", "threads-insights", "--scheduled"])
        self.assertEqual(job["EnvironmentVariables"]["PYTHONPATH"], "/repo")
        self.assertEqual(job["StartCalendarInterval"], {"Hour": 9, "Minute": 20})

    def test_scheduled_run_refreshes_logs_and_commits_only_the_tsv(self):
        calls = []
        with mock.patch.object(threads, "token", return_value="tok"), \
             mock.patch.object(threads, "refresh", side_effect=ValueError("too new")), \
             mock.patch.object(threads, "log_insights", side_effect=lambda tok, path: calls.append(("log", tok, path)) or []), \
             mock.patch.object(threads, "log_reply_insights", side_effect=lambda tok, path: calls.append(("replies", tok, path)) or []), \
             mock.patch("leadkit.aso_cli.commit_ranks", side_effect=lambda repo, paths, day, message=None: calls.append(("commit", paths, message))):
            threads.scheduled_insights(day="2026-11-17")
        self.assertEqual(calls, [("log", "tok", threads.INSIGHTS_TSV), ("replies", "tok", threads.REPLIES_TSV),
                                 ("commit", [threads.INSIGHTS_TSV, threads.REPLIES_TSV],
                                  "threads: daily insights 2026-11-17")])

    def test_a_failing_replies_step_still_logs_and_commits_the_posts(self):
        calls = []
        with mock.patch.object(threads, "token", return_value="tok"), \
             mock.patch.object(threads, "refresh", side_effect=ValueError("too new")), \
             mock.patch.object(threads, "log_insights", side_effect=lambda tok, path: calls.append("log") or []), \
             mock.patch.object(threads, "log_reply_insights", side_effect=ApiError(500, "down")), \
             mock.patch("leadkit.aso_cli.commit_ranks", side_effect=lambda repo, paths, day, message=None: calls.append(paths)):
            threads.scheduled_insights(day="2026-11-17")
        self.assertEqual(calls, ["log", [threads.INSIGHTS_TSV, threads.REPLIES_TSV]])

    def test_token_needs_no_product(self):
        self.assertEqual(threads.token_file(None).name, "threads_token")


if __name__ == "__main__":
    unittest.main()
