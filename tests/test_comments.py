"""The comment watcher: Reddit comments that use a product's phrases, as leads.

F5Bot emails these within about two hours but caps them at 20 alerts a day,
which a common phrase reaches. Arctic Shift won't search comment text across
Reddit or inside a busy sub (the search times out), so a run lists each sub's
recent comments and matches the phrases locally. A fake `get` keeps
these off the network.

    bin/test
"""
import sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import comments  # noqa: E402
from helpers import TempProduct, ago  # noqa: E402

NOW = int(time.time())


def comment(cid, sub, link, body, hours=0.5, author="someone"):
    return {"id": cid, "subreddit": sub, "link_id": f"t3_{link}", "body": body, "author": author,
            "created_utc": NOW - int(hours * 3600)}


def post(pid, sub, title, days=0.5, author="asker"):
    return {"id": pid, "subreddit": sub, "title": title, "selftext": "", "author": author,
            "created_utc": NOW - int(days * 86400), "num_comments": 3}


def fake(listing, posts):
    """A `get` serving one page of comments per sub and the posts by id."""
    asked = []

    def get(path, params):
        asked.append((path, params))
        if path == "comments/search":
            return [c for c in listing if c["subreddit"] == params["subreddit"]
                    and c["created_utc"] >= params["after"]]
        if path == "posts/ids":
            ids = params["ids"].split(",")
            return [p for p in posts if p["id"] in ids]
        raise AssertionError(path)
    get.asked = asked
    return get


class FindTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")
        self.t.p.cfg.COMMENT_PHRASES = ['"climbing log"', '"track my sends"']
        self.t.p.cfg.COMMENT_SUBS = ["climbing", "bouldering"]
        self.t.write("Reddit", [{"url": "https://www.reddit.com/r/climbing/comments/old1/", "status": "skip"}])

    def tearDown(self):
        self.t.close()

    def find(self, listing, posts, **kw):
        return comments.find(self.t.p, get=fake(listing, posts), now=NOW, **kw)

    def test_a_phrase_in_a_comment_makes_its_thread_a_new_lead(self):
        rows = self.find([comment("c1", "climbing", "p1", "Honestly, keep a climbing log every session.")],
                         [post("p1", "climbing", "Stuck at V4")])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["url"], "https://www.reddit.com/r/climbing/comments/p1/")
        self.assertEqual((r["title"], r["status"], r["kind"], r["author"]), ("Stuck at V4", "new", "domain", "asker"))
        self.assertIn('"climbing log"', r["notes"])
        self.assertIn("/comments/p1/comment/c1/", r["notes"])
        self.assertIn("keep a climbing log", r["notes"])

    def test_comments_without_a_phrase_are_ignored(self):
        self.assertEqual(self.find([comment("c1", "climbing", "p1", "Nice send")], [post("p1", "climbing", "t")]), [])

    def test_threads_already_in_the_file_are_skipped(self):
        self.assertEqual(self.find([comment("c1", "climbing", "old1", "climbing log")], [post("old1", "climbing", "t")]), [])

    def test_our_own_comments_and_posts_are_skipped(self):
        self.assertEqual(self.find([comment("c1", "climbing", "p1", "climbing log", author="MyDevAccount")],
                                   [post("p1", "climbing", "t")]), [])
        self.assertEqual(self.find([comment("c1", "climbing", "p2", "climbing log")],
                                   [post("p2", "climbing", "t", author="MyDevAccount")]), [])

    def test_old_threads_are_skipped(self):
        # A comment today on a two-week-old thread: nobody reads that thread now.
        self.assertEqual(self.find([comment("c1", "climbing", "p1", "climbing log")],
                                   [post("p1", "climbing", "t", days=14)]), [])

    def test_only_comments_inside_the_window_count(self):
        self.assertEqual(self.find([comment("c1", "climbing", "p1", "climbing log", hours=10)],
                                   [post("p1", "climbing", "t")], hours=3), [])

    def test_one_row_per_thread_and_one_lookup_for_all_threads(self):
        get = fake([comment("c1", "climbing", "p1", "climbing log"),
                    comment("c2", "climbing", "p1", "track my sends"),
                    comment("c3", "bouldering", "p2", "Start a CLIMBING LOG")],
                   [post("p1", "climbing", "a"), post("p2", "bouldering", "b")])
        rows = comments.find(self.t.p, get=get, now=NOW)
        self.assertEqual(sorted(r["title"] for r in rows), ["a", "b"])
        self.assertEqual(sum(1 for path, _ in get.asked if path == "posts/ids"), 1)

    def test_a_sub_that_fails_does_not_stop_the_run(self):
        def get(path, params):
            if path == "comments/search" and params["subreddit"] == "climbing":
                raise comments.arctic.Error("Timeout")
            return fake([comment("c3", "bouldering", "p2", "climbing log")], [post("p2", "bouldering", "b")])(path, params)
        self.assertEqual([r["title"] for r in comments.find(self.t.p, get=get, now=NOW)], ["b"])


    def test_a_page_that_fails_after_the_first_keeps_what_came_back(self):
        first = [comment(f"c{i}", "climbing", "p1" if i == 0 else f"q{i}", "climbing log" if i == 0 else "hi",
                         hours=i * 0.01) for i in range(100)]
        posts = [post("p1", "climbing", "kept")]

        def get(path, params):
            if path == "comments/search" and "before" in params:
                raise comments.arctic.Error("Timeout")
            if path == "comments/search":
                return first if params["subreddit"] == "climbing" else []
            return fake([], posts)(path, params)
        self.assertEqual([r["title"] for r in comments.find(self.t.p, get=get, now=NOW)], ["kept"])

class RunTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct("cragbook")
        self.t.p.cfg.COMMENT_PHRASES = ['"climbing log"']
        self.t.p.cfg.COMMENT_SUBS = ["climbing"]
        self.t.write("Reddit", [])
        self.get = fake([comment("c1", "climbing", "p1", "climbing log")], [post("p1", "climbing", "Stuck")])

    def tearDown(self):
        self.t.close()

    def test_run_appends_and_a_second_run_adds_nothing(self):
        self.assertEqual(len(comments.run(self.t.p, get=self.get, now=NOW)), 1)
        self.assertEqual(comments.run(self.t.p, get=self.get, now=NOW), [])
        rows = self.t.read("Reddit")
        self.assertEqual([(r["status"], r["found"]) for r in rows], [("new", ago(0))])

    def test_scheduled_triages_new_threads_and_banners_only_drafts(self):
        calls, banners = [], []

        def claude(prompt, repo):
            calls.append(prompt)
            # What the headless session does: draft the thread with `leads set`.
            from leadkit import rows
            rows.set_row(self.t.p, "https://www.reddit.com/r/climbing/comments/p1/", {"status": "draft", "reply": "Try this."})

        comments.scheduled(self.t.p, get=self.get, now=NOW, posts=lambda p: [], claude=claude,
                           notify=lambda title, text, command=None: banners.append((title, text, command)), commit=lambda *a: None)
        self.assertEqual(len(calls), 1)
        self.assertIn("https://www.reddit.com/r/climbing/comments/p1/", calls[0])
        self.assertEqual(len(banners), 1)
        self.assertIn("Stuck", banners[0][1])
        self.assertIn("-m leadkit.cli -p cragbook drafts", banners[0][2])

    def test_scheduled_triages_what_the_post_search_finds_too(self):
        # The job should catch anything a leads pass would draft,
        # and a pass drafts mostly from the post search and its near misses.
        calls, banners = [], []
        url = "https://www.reddit.com/r/climbharder/comments/q9/"

        def posts(p):
            from leadkit import tsv
            row = {"found": ago(0), "subreddit": "climbharder", "author": "a", "title": "Soft grades at my gym",
                   "url": url, "status": "new", "kind": "domain", "notes": "Near miss [1]. body"}
            tsv.append(p.reddit_tsv, [row], comments.reddit.FIELDS)
            return [row]

        def claude(prompt, repo):
            calls.append(prompt)
            from leadkit import rows
            rows.set_row(self.t.p, url, {"status": "draft", "reply": "Try this."})

        comments.scheduled(self.t.p, get=fake([], []), now=NOW, posts=posts, claude=claude,
                           notify=lambda title, text, command=None: banners.append(text), commit=lambda *a: None)
        self.assertEqual(len(calls), 1)
        self.assertIn(url, calls[0])
        self.assertIn("Near miss", calls[0])
        self.assertEqual(len(banners), 1)
        self.assertIn("Soft grades at my gym", banners[0])

    def test_scheduled_stays_quiet_when_everything_is_skipped(self):
        banners = []

        def claude(prompt, repo):
            from leadkit import rows
            rows.set_row(self.t.p, "https://www.reddit.com/r/climbing/comments/p1/", {"status": "skip"})

        comments.scheduled(self.t.p, get=self.get, now=NOW, posts=lambda p: [], claude=claude,
                           notify=lambda *a: banners.append(a), commit=lambda *a: None)
        self.assertEqual(banners, [])

    def test_scheduled_does_nothing_without_new_threads(self):
        comments.run(self.t.p, get=self.get, now=NOW)
        calls = []
        comments.scheduled(self.t.p, get=self.get, now=NOW, posts=lambda p: [], claude=lambda *a: calls.append(a),
                           notify=lambda *a: calls.append(a), commit=lambda *a: calls.append(a))
        self.assertEqual(calls, [])


class JobTest(unittest.TestCase):
    def test_the_job_runs_hourly_with_leads_and_claude_on_its_path(self):
        import plistlib
        job = plistlib.loads(comments.job_plist("cragbook", Path("/lk"), "/py", Path("/log")))
        self.assertEqual(job["ProgramArguments"], ["/py", "-m", "leadkit.cli", "-p", "cragbook", "comments", "--scheduled"])
        self.assertEqual(job["StartInterval"], 3600)
        self.assertIn("/lk/bin", job["EnvironmentVariables"]["PATH"])
        self.assertIn(".local/bin", job["EnvironmentVariables"]["PATH"])


if __name__ == "__main__":
    unittest.main()
