"""The Reddit engine's parts that don't need the network.

    bin/test
"""
import shutil, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import product, reddit, tsv  # noqa: E402
from helpers import TempProduct  # noqa: E402

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>newest submissions : gamedev</title>
  <entry>
    <author><name>/u/someone</name></author>
    <category term="gamedev" label="r/gamedev"/>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;I can&amp;#39;t draw anything &amp;amp; need a logo.&lt;/p&gt;&lt;/div&gt;</content>
    <id>t3_abc123</id>
    <link href="https://www.reddit.com/r/gamedev/comments/Abc123/need_logo/"/>
    <published>2026-10-15T09:30:00+00:00</published>
    <updated>2026-10-15T09:31:00+00:00</updated>
    <title>Need a logo for my game</title>
  </entry>
</feed>
"""


def atom(*items):
    """A feed of (url, sub, published[, comment text]) entries, the shape Reddit's user feeds have."""
    def content(text):
        return f'<content type="html">&lt;p&gt;{text}&lt;/p&gt;</content>' if text else ""
    body = "".join(f"""<entry><author><name>/u/MyDevAccount</name></author>
<category term="{i[1]}"/><link href="{i[0]}"/><published>{i[2]}</published><title>t</title>{content(i[3] if len(i) > 3 else "")}</entry>"""
                   for i in items)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode()


class EntriesTest(unittest.TestCase):
    def test_parses_one_atom_entry(self):
        (e,) = list(reddit.entries(FEED))
        self.assertEqual(e["author"], "someone")
        self.assertEqual(e["title"], "Need a logo for my game")
        self.assertEqual(e["url"], "https://www.reddit.com/r/gamedev/comments/Abc123/need_logo/")
        self.assertEqual(e["sub"], "gamedev")
        self.assertEqual(e["stamp"], "2026-10-15T09:30:00+00:00")
        self.assertEqual(e["posted"], "2026-10-15")
        self.assertEqual(" ".join(e["body"].split()), "I can't draw anything & need a logo.")


class PostIdTest(unittest.TestCase):
    def test_full_and_short_urls_share_an_id(self):
        self.assertEqual(reddit.post_id("https://www.reddit.com/r/GameDev/comments/Abc123/need_logo/"), "abc123")
        self.assertEqual(reddit.post_id("https://redd.it/x/comments/abc123/"), "abc123")

    def test_no_id(self):
        self.assertIsNone(reddit.post_id("https://www.reddit.com/r/gamedev/"))
        self.assertIsNone(reddit.post_id(None))


class SubmitSubTest(unittest.TestCase):
    def test_own_post_rows_name_their_sub(self):
        self.assertEqual(reddit.submit_sub("https://www.reddit.com/r/iPadApps/submit"), "ipadapps")
        self.assertIsNone(reddit.submit_sub("https://www.reddit.com/r/gamedev/comments/abc/"))


class FeedsTest(unittest.TestCase):
    def test_knitwit_reads_its_groups_and_skips_excluded_subs(self):
        p = product.Product("knitwit")
        # Ask for the excluded subs by name too: they still stay out.
        urls = reddit.feeds(p, subreddits=p.cfg.SUBREDDITS + sorted(p.cfg.EXCLUDED))
        self.assertTrue(any("/r/ipad+iosapps/search.rss" in u for u in urls), urls)
        for sub in p.cfg.EXCLUDED:
            self.assertFalse(any(sub in u.lower() for u in urls), sub)

    def test_cragbook_reads_its_new_feeds_and_searches_every_sub(self):
        p = product.Product("cragbook")
        urls = reddit.feeds(p)
        for sub in p.cfg.NEW_FEEDS:
            self.assertIn(f"https://www.reddit.com/r/{sub}/new.rss?limit=100", urls)
        searched = {s for u in urls if "/search.rss" in u and "/r/" in u
                    for s in u.split("/r/")[1].split("/")[0].split("+")}
        for sub in p.cfg.SUBREDDITS:
            self.assertIn(sub, searched)

    def test_every_search_asks_for_100_results(self):
        # Without a limit search.rss returns 25, which for "app OR apps" across
        # a product's busy subs reaches back only a few days of the week asked for.
        for name in ("cragbook", "knitwit"):
            for u in reddit.feeds(product.Product(name)):
                if "/search.rss" in u:
                    self.assertIn("limit=100", u)

    def test_cragbook_has_no_device_search(self):
        # Device searches (tablets, foldables) find hardware posts and other
        # makers' launches, nothing a climbing logbook can answer, so Cragbook
        # has none on Reddit or Threads.
        p = product.Product("cragbook")
        urls = reddit.feeds(p)
        for word in ("ipad", "fold", "tablet"):
            self.assertFalse(any(word in u.lower() for u in urls), word)
        self.assertNotIn("tablet", p.get("THREADS_SEARCHES", {}))
        self.assertNotIn("fold", p.get("THREADS_SEARCHES", {}))

    def test_cragbook_searches_app_subs_without_reading_them_new(self):
        urls = reddit.feeds(product.Product("cragbook"))
        self.assertTrue(any("iosapps" in u and "/search.rss" in u for u in urls))
        self.assertFalse(any("iosapps" in u and "/new.rss" in u for u in urls))


def entry(sub, title, body="", pid="zz9"):
    stamp = datetime.now(timezone.utc).isoformat()
    return (f"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<author><name>/u/asker</name></author><category term="{sub}"/>
<content type="html">&lt;p&gt;{body}&lt;/p&gt;</content>
<link href="https://www.reddit.com/r/{sub}/comments/{pid}/x/"/>
<published>{stamp}</published><title>{title}</title></entry></feed>""").encode()


class RulesUncheckedTest(unittest.TestCase):
    """A sub added to the watcher before anyone has read its sidebar tags its
    leads, so the first reply there waits for a rules check."""

    def setUp(self):
        self.t = TempProduct("cragbook")
        self.t.p.cfg.RULES_UNCHECKED = {"tradclimbing"}

    def tearDown(self):
        self.t.close()

    def lead(self, sub):
        feed = entry(sub, "Plateaued at V4, need a training plan", "Not improving for a year.")
        rows = reddit.watch(self.t.p, dry_run=True, pause=0, subreddits=[sub], source="reddit",
                            fetch=lambda url, pause, agent=None: feed)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_a_lead_from_an_unchecked_sub_says_so(self):
        self.assertTrue(self.lead("tradclimbing")["notes"].startswith("Rules unchecked for r/tradclimbing"))

    def test_a_checked_sub_is_untagged(self):
        self.assertNotIn("Rules unchecked", self.lead("climbing")["notes"])


class MarkPostedTest(unittest.TestCase):
    """mark_posted on a copy of a product with a two-row TSV and recorded feeds."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = product.Product("knitwit")
        self.p.dir = self.tmp
        self.p.cfg.LEADS_DIR = "leads"
        (self.tmp / "leads").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        product.Product("knitwit")  # reload the real config for other tests

    def run_with(self, rows, comments, submitted=()):
        tsv.write(self.p.reddit_tsv, reddit.FIELDS, [dict.fromkeys(reddit.FIELDS, "") | r for r in rows])

        def fetch(url, pause, agent=None):
            return atom(*(comments if "/comments/" in url else submitted))
        reddit.mark_posted(self.p, 0, fetch)
        return tsv.read(self.p.reddit_tsv)[1]

    def test_a_comment_marks_its_draft(self):
        (r,) = self.run_with([{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
                             [("https://www.reddit.com/r/a/comments/x1/t/c9/", "a", "2026-10-25T00:00:00+00:00")])
        self.assertEqual(r["status"], "posted")
        self.assertIn("Comment: https://www.reddit.com/r/a/comments/x1/t/c9/", r["notes"])

    # When two apps draft for the same thread, one app's reply must not mark
    # the other app's draft as posted.
    def test_a_comment_naming_another_app_does_not_mark_this_apps_draft(self):
        (r,) = self.run_with([{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
                             [("https://www.reddit.com/r/a/comments/x1/t/c9/", "a", "2026-10-25T00:00:00+00:00",
                               "I'm building Mossling, a tiny moss terrarium for your Home Screen.")])
        self.assertEqual(r["status"], "draft")

    def test_a_comment_naming_this_app_and_another_still_counts(self):
        (r,) = self.run_with([{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
                             [("https://www.reddit.com/r/a/comments/x1/t/c9/", "a", "2026-10-25T00:00:00+00:00",
                               f"{self.p.title} works a bit like Mossling's widget.")])
        self.assertEqual(r["status"], "posted")

    def test_a_comment_naming_no_app_still_counts(self):
        (r,) = self.run_with([{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
                             [("https://www.reddit.com/r/a/comments/x1/t/c9/", "a", "2026-10-25T00:00:00+00:00",
                               "Try a stitch marker every ten rows first.")])
        self.assertEqual(r["status"], "posted")

    def test_a_follow_up_is_not_marked_by_the_earlier_reply(self):
        reply = "https://www.reddit.com/r/a/comments/x1/t/c9/"
        rows = self.run_with([
            {"url": "https://www.reddit.com/r/a/comments/x1/", "status": "posted", "notes": f"Comment: {reply}"},
            {"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft", "notes": "follow-up"},
        ], [(reply, "a", "2026-10-25T00:00:00+00:00")])
        self.assertEqual(rows[1]["status"], "draft")

    def test_an_own_post_marks_its_submit_row(self):
        (r,) = self.run_with(
            [{"url": "https://www.reddit.com/r/ipadapps/submit", "status": "draft", "found": "2026-10-24"}],
            [], [("https://www.reddit.com/r/ipadapps/comments/p1/knitwit/", "ipadapps", "2026-10-25T00:00:00+00:00")])
        self.assertEqual(r["status"], "posted")
        self.assertTrue(r["notes"].startswith("Post: "))

    # The feeds can sit in 429 waits for minutes while another session runs
    # `leads set` to add a draft; mark_posted must not write its earlier read over it.
    def test_a_row_added_while_the_feeds_load_survives(self):
        tsv.write(self.p.reddit_tsv, reddit.FIELDS, [dict.fromkeys(reddit.FIELDS, "") | {
            "url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}])
        added = dict.fromkeys(reddit.FIELDS, "") | {"url": "https://www.reddit.com/r/a/comments/x2/", "status": "draft"}

        def fetch(url, pause, agent=None):
            if "/comments/" in url:
                tsv.append(self.p.reddit_tsv, [added], reddit.FIELDS)
                return atom(("https://www.reddit.com/r/a/comments/x1/t/c9/", "a", "2026-10-25T00:00:00+00:00"))
            return atom()
        reddit.mark_posted(self.p, 0, fetch)
        rows = {r["url"]: r["status"] for r in tsv.read(self.p.reddit_tsv)[1]}
        self.assertEqual(rows, {"https://www.reddit.com/r/a/comments/x1/": "posted",
                                "https://www.reddit.com/r/a/comments/x2/": "draft"})

    # When the account's comment feed answers 404, posted replies would stay
    # open on the drafts page; Arctic Shift's archive stands in for the feed.
    def run_on_archive(self, rows, comments=(), posts=()):
        tsv.write(self.p.reddit_tsv, reddit.FIELDS, [dict.fromkeys(reddit.FIELDS, "") | r for r in rows])
        calls = []

        def get(path, params, pause=1.0):
            calls.append((path, params))
            return list(comments if path == "comments/search" else posts)
        reddit.mark_posted(self.p, 0, lambda url, pause, agent=None: None, arctic_get=get)
        return tsv.read(self.p.reddit_tsv)[1], calls

    def test_a_dead_comment_feed_falls_back_to_arctic_shift(self):
        (r,), calls = self.run_on_archive(
            [{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
            [{"link_id": "t3_x1", "subreddit": "a", "created_utc": 1792800000,
              "permalink": "/r/a/comments/x1/t/c9/", "body": "Try a stitch marker first."}])
        self.assertEqual(r["status"], "posted")
        self.assertIn("Comment: https://www.reddit.com/r/a/comments/x1/t/c9/", r["notes"])
        self.assertEqual(calls[0][1]["author"], reddit.settings.REDDIT_REPLY_ACCOUNT)

    def test_the_fallback_still_skips_a_comment_for_another_app(self):
        (r,), _ = self.run_on_archive(
            [{"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}],
            [{"link_id": "t3_x1", "subreddit": "a", "created_utc": 1792800000,
              "permalink": "/r/a/comments/x1/t/c9/", "body": "I'm building Mossling, a moss terrarium."}])
        self.assertEqual(r["status"], "draft")

    def test_a_dead_submitted_feed_falls_back_to_arctic_shift(self):
        (r,), _ = self.run_on_archive(
            [{"url": "https://www.reddit.com/r/ipadapps/submit", "status": "draft", "found": "2026-10-24"}],
            posts=[{"id": "p1", "subreddit": "ipadapps", "created_utc": 1792886400, "title": "Knitwit"}])
        self.assertEqual(r["status"], "posted")
        self.assertTrue(r["notes"].startswith("Post: https://www.reddit.com/r/ipadapps/comments/p1/"))

    def test_an_archive_failure_marks_nothing(self):
        tsv.write(self.p.reddit_tsv, reddit.FIELDS,
                  [dict.fromkeys(reddit.FIELDS, "") | {"url": "https://www.reddit.com/r/a/comments/x1/", "status": "draft"}])

        def get(path, params, pause=1.0):
            raise reddit.arctic.Error("down")
        self.assertEqual(reddit.mark_posted(self.p, 0, lambda u, p, a=None: None, arctic_get=get), 0)
        self.assertEqual(tsv.read(self.p.reddit_tsv)[1][0]["status"], "draft")

    def test_an_older_own_post_does_not_count(self):
        (r,) = self.run_with(
            [{"url": "https://www.reddit.com/r/ipadapps/submit", "status": "draft", "found": "2026-10-26"}],
            [], [("https://www.reddit.com/r/ipadapps/comments/p1/old/", "ipadapps", "2026-10-20T00:00:00+00:00")])
        self.assertEqual(r["status"], "draft")


class SearchRefusedTest(unittest.TestCase):
    """Reddit answers anonymous search.rss with 403, after a 429
    that costs a minute's wait. One refusal skips the run's other searches, so a
    pass doesn't spend 17 minutes collecting eleven refusals."""

    def setUp(self):
        self.t = TempProduct("cragbook")

    def tearDown(self):
        self.t.close()

    def test_one_403_skips_the_other_searches_but_not_new_feeds(self):
        asked = []

        def fetch(url, pause, agent=None):
            asked.append(url)
            return reddit.FORBIDDEN if "/search.rss" in url else entry("climbing", "t", "b")
        reddit.watch(self.t.p, dry_run=True, pause=0, source="reddit", fetch=fetch)
        urls = reddit.feeds(self.t.p)
        searches = [u for u in asked if "/search.rss" in u]
        self.assertEqual(len(searches), 1)
        self.assertEqual([u for u in asked if "/new.rss" in u], [u for u in urls if "/new.rss" in u])

    def test_forbidden_is_falsy_so_other_callers_treat_it_as_no_data(self):
        self.assertFalse(reddit.FORBIDDEN)
