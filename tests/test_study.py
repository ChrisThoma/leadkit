"""What does well: `leads study`, with fake data so nothing touches the network.

    bin/test
"""
import re, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import study  # noqa: E402

NOW = int(time.time())


def raw(pid, sub="iosapps", title="A post", score=1, comments=0, days=5, **kw):
    x = {"id": pid, "subreddit": sub, "title": title, "selftext": "", "author": "a",
         "created_utc": NOW - days * 86400, "score": score, "num_comments": comments,
         "upvote_ratio": 1.0, "link_flair_text": None, "post_hint": None, "is_self": True,
         "domain": f"self.{sub}", "url": "", "removed_by_category": None, "is_video": False}
    x.update(kw)
    return x


class FormatTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(study.reddit_format(raw("a")), "text")
        self.assertEqual(study.reddit_format(raw("a", is_self=False, post_hint="image", domain="i.redd.it")), "image")
        self.assertEqual(study.reddit_format(raw("a", is_self=False, is_video=True, domain="v.redd.it")), "video")
        self.assertEqual(study.reddit_format(raw("a", is_self=False, url="https://www.reddit.com/gallery/x")), "gallery")
        self.assertEqual(study.reddit_format(raw("a", is_self=False, domain="youtube.com", post_hint="rich:video")), "youtube")
        self.assertEqual(study.reddit_format(raw("a", is_self=False, domain="apps.apple.com")), "link")


class KindTest(unittest.TestCase):
    def test_kinds(self):
        self.assertIn("question", study.kinds("Any app for counting rows?"))
        self.assertIn("ask-recs", study.kinds("Looking for recommendations: first sweater patterns"))
        self.assertIn("i-made", study.kinds("I made a tiny row counter for my sister"))
        self.assertIn("list", study.kinds("5 tiny apps for knitters"))
        self.assertIn("app-link", study.kinds("Try it", "https://apps.apple.com/app/id123"))
        self.assertEqual(study.kinds("Sunday thoughts"), ["other"])


class RedditRowsTest(unittest.TestCase):
    def test_young_and_stickied_posts_are_left_out(self):
        rows = study.reddit_rows([raw("old", days=5), raw("young", days=1), raw("pin", stickied=True)])
        self.assertEqual([r["id"] for r in rows], ["old"])

    def test_removed_is_kept_and_flagged(self):
        (r,) = study.reddit_rows([raw("x", removed_by_category="moderator")])
        self.assertEqual(r["removed"], "moderator")


class WinnersTest(unittest.TestCase):
    def rows(self):
        posts = [raw(f"p{i}", score=i, title="How do I?" if i < 18 else "I made this") for i in range(20)]
        posts.append(raw("gone", score=500, removed_by_category="moderator"))
        return study.reddit_rows(posts)

    def test_top_tenth_per_sub_ignores_removed(self):
        rows = study.mark_winners(self.rows(), "score")
        self.assertEqual(sorted(r["id"] for r in rows if r["winner"]), ["p18", "p19"])
        self.assertFalse(next(r for r in rows if r["id"] == "gone")["winner"])

    def test_lift_shows_what_winners_share(self):
        rows = study.mark_winners(self.rows(), "score")
        table = dict((k, (w, a)) for k, w, a, _ in study.lifts(rows, "kinds"))
        self.assertEqual(table["i-made"][0], 1.0)  # every winner
        self.assertAlmostEqual(table["i-made"][1], 0.1)  # a tenth of the live posts

    def test_small_subs_have_no_winners(self):
        rows = study.mark_winners(study.reddit_rows([raw(f"p{i}", score=i) for i in range(5)]), "score")
        self.assertFalse(any(r["winner"] for r in rows))


class ThreadsTest(unittest.TestCase):
    def test_counts_with_k_and_m(self):
        self.assertEqual(study.count("4.8K"), 4800)
        self.assertEqual(study.count("1.2M"), 1200000)
        self.assertEqual(study.count(""), 0)
        self.assertEqual(study.count("1,024"), 1024)

    def test_rows_dedupe_by_path_and_keep_the_higher_counts(self):
        items = [{"path": "/@a/post/X", "author": "a", "date": "2026-11-01T10:00:00.000Z", "text": "4 indie apps",
                  "likes": "10", "replies": "2", "reposts": "", "shares": "", "media": "image", "tag": "",
                  "query": "indie app"},
                 {"path": "/@a/post/X", "author": "a", "date": "2026-11-01T10:00:00.000Z", "text": "4 indie apps",
                  "likes": "12", "replies": "2", "reposts": "1", "shares": "", "media": "image", "tag": "",
                  "query": "app"}]
        (r,) = study.threads_rows(items)
        self.assertEqual((r["likes"], r["reposts"], r["engagement"]), (12, 1, 12 + 2 * 3 + 1 * 2))
        self.assertIn("list", r["kinds"])


class StudyRedditTest(unittest.TestCase):
    def test_writes_report_and_tsv(self):
        import tempfile
        from types import SimpleNamespace
        d = Path(tempfile.mkdtemp())
        p = SimpleNamespace(title="Knitwit", dir=d, get=lambda k, default=None: default)
        posts = [raw(f"p{i}", sub="knitting", score=i, title="I made a row counter app" if i == 19 else "Help?") for i in range(20)]
        md = study.study_reddit(p, days=30, subs=["knitting"], labels=False, get=lambda path, params: posts if "before" in params and params["before"] > NOW - 3 * 86400 else [])
        text = md.read_text()
        self.assertIn("r/knitting", text)
        self.assertIn("I made a row counter app", text)
        self.assertTrue(list((d / "study").glob("reddit-*.tsv")))

    def test_quiet_and_empty_subs_are_not_blamed_on_the_cap(self):
        # A sub with 2 posts over 19 days is quiet, not capped; an empty one is named.
        rows = study.mark_winners(study.reddit_rows([raw("a", sub="Sock_Knitting", days=5),
                                                     raw("b", sub="Sock_Knitting", days=19)]), "score")
        text = study.reddit_report(type("P", (), {"title": "Kw"}), rows,
                                   {"Sock_Knitting": (2, 19), "big": (study.MAX_PAGES * 100, 12), "Brochet": (0, 0)}, 30)
        self.assertNotIn("r/Sock_Knitting (the", text)
        self.assertNotIn("r/Sock_Knitting, ", text.split("post cap")[0].split("Only part")[-1])
        self.assertIn("Only part of the window was read for r/big (the", text)
        self.assertIn("No posts in the window: r/Brochet", text)


class ReceiveTest(unittest.TestCase):
    """The dump script posts a form; the receiver saves it."""

    def test_form_post_is_saved(self):
        import tempfile, threading, urllib.parse, urllib.request
        from types import SimpleNamespace
        d = Path(tempfile.mkdtemp())
        p = SimpleNamespace(dir=d)
        port = 18000 + NOW % 1000
        result = {}
        t = threading.Thread(target=lambda: result.update(path=study.receive(p, port=port, timeout=20)))
        t.start()
        time.sleep(0.3)
        posts = [{"path": "/@a/post/X", "lines": ["a", "1d", "hi"], "likes": "3"}]
        body = urllib.parse.urlencode({"posts": __import__("json").dumps(posts)}).encode()
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", data=body).read()
        t.join()
        self.assertEqual(__import__("json").loads(result["path"].read_text()), posts)

    def test_dump_js_never_clears_storage(self):
        js = study.dump_js("http://127.0.0.1:1/")
        self.assertNotIn("removeItem", js)
        self.assertIn("http://127.0.0.1:1/", js)


class ArcticRetryTest(unittest.TestCase):
    def test_incomplete_read_is_retried(self):
        import http.client, io, json
        from unittest import mock
        from leadkit import arctic
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"partial")
            return Resp(json.dumps({"data": [1]}).encode())
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            self.assertEqual(arctic.get("posts/search", {}), [1])
        self.assertEqual(len(calls), 2)


class LabelTest(unittest.TestCase):
    """Hooks come from claude -p; here a fake stands in."""

    def rows(self):
        rows = [{"id": f"p{i}", "text": f"post {i}", "winner": i >= 18, "removed": "", "engagement": i}
                for i in range(40)]
        return rows

    def test_sample_is_winners_plus_as_many_controls(self):
        rows = self.rows()
        sample = study.label_sample(rows, cap=50)
        self.assertEqual(sum(r["winner"] for r in sample), 22)
        self.assertEqual(sum(not r["winner"] for r in sample), 18)

    def test_parse_keeps_known_hooks_only(self):
        out = "p18\thot-take\tsays what knitters think\np19\tnonsense\tx\njunk line\n"
        self.assertEqual(study.parse_labels(out), {"p18": ("hot-take", "says what knitters think"),
                                                   "p19": ("other", "x")})

    def test_label_sets_hook_and_table_compares_winners_to_controls(self):
        rows = self.rows()

        def fake(prompt, model):
            ids = re.findall(r"^(p\d+)\t", prompt, re.M)
            return "\n".join(f"{i}\t{'relatable-humor' if int(i[1:]) >= 18 else 'crowd-question'}\twhy" for i in ids)
        labelled = study.label(rows, ask=fake)
        table = {v: (w, c) for v, w, c, _ in study.hook_lifts(labelled)}
        self.assertEqual(table["relatable-humor"], (1.0, 0.0))
        self.assertEqual(table["crowd-question"], (0.0, 1.0))


class CleanLinesTest(unittest.TestCase):
    """The text lines of a Threads search result, in the shape the page gives them."""

    def test_tag_date_and_counts_come_off(self):
        lines = ["example.knitter", "Tech Threads", "1d", "Got an app nobody has seen yet?",
                 "Post the name and the one thing it does.", "1 / 2", "20", "60", "2"]
        self.assertEqual(study.clean_lines("example.knitter", lines),
                         ("Tech Threads", "Got an app nobody has seen yet? Post the name and the one thing it does."))

    def test_no_tag(self):
        lines = ["sample_studio", "10/10/26", "4 tiny apps for knitters 🧶", "1.2K", "30", "200", "100"]
        self.assertEqual(study.clean_lines("sample_studio", lines), ("", "4 tiny apps for knitters 🧶"))


if __name__ == "__main__":
    unittest.main()
