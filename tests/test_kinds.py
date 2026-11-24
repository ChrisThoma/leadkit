"""Lead kinds: "domain" asks (the app's own subject, each product's config) and
"app" asks (threads inviting any app, shared by every product in kinds.py).

    bin/test
"""
import io, sys, unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from leadkit import drafts, kinds, product, reddit, threads, tsv  # noqa: E402
from helpers import TempProduct  # noqa: E402


def feed(sub, title, body="", pid="zz9", hours=2):
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return (f"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<author><name>/u/asker</name></author><category term="{sub}"/>
<content type="html">&lt;p&gt;{body}&lt;/p&gt;</content>
<link href="https://www.reddit.com/r/{sub}/comments/{pid}/x/"/>
<published>{stamp}</published><title>{title}</title></entry></feed>""").encode()


class SharedSearchesTest(unittest.TestCase):
    def test_every_product_gets_the_shared_app_searches(self):
        # Cragbook opts out (APP_LEADS = False), so only products that keep app leads.
        for name in product.names():
            p = product.Product(name)
            if not kinds.enabled(p):
                continue
            kinds_by_url = dict(reddit.feed_kinds(p))
            self.assertIn("app", kinds_by_url.values(), name)
            self.assertIn("domain", kinds_by_url.values(), name)
            self.assertEqual(threads.groups(p)["showcase"], kinds.APP["threads"]["showcase"], name)

    def test_showcase_lives_only_in_kinds(self):
        # One list for every app, so a fix (dropping "promote your product")
        # reaches them all.
        for name in product.names():
            self.assertNotIn("showcase", product.Product(name).get("THREADS_SEARCHES", {}), name)

    def test_a_product_can_opt_out(self):
        t = TempProduct("cragbook")
        try:
            t.p.cfg.APP_LEADS = False
            self.assertNotIn("app", dict(reddit.feed_kinds(t.p)).values())
            self.assertNotIn("showcase", threads.groups(t.p))
        finally:
            t.close()
            product.Product("cragbook")

    def test_cragbook_has_no_app_leads(self):
        # No "promote your app" posts for Cragbook, least of all on Threads.
        p = product.Product("cragbook")
        self.assertNotIn("app", dict(reddit.feed_kinds(p)).values())
        self.assertNotIn("showcase", threads.groups(p))

    def test_searches_print_each_groups_kind(self):
        out = io.StringIO()
        with redirect_stdout(out):
            threads.searches(product.Product("knitwit"))
        self.assertIn("# showcase (app:", out.getvalue())
        self.assertIn("# core (domain)", out.getvalue())


class WatchTest(unittest.TestCase):
    """watch() scores each feed with its own kind's tables, age limit and floor."""

    def setUp(self):
        # Cragbook's fixture config turns app leads off; these tests
        # need the app feeds, so switch them back on for the temp copy.
        self.t = TempProduct("cragbook")
        self.t.p.cfg.APP_LEADS = True

    def tearDown(self):
        self.t.close()
        product.Product("cragbook")

    def run_feeds(self, by_kind, dry_run=True):
        def fetch(url, pause, agent=None):
            kind = dict(reddit.feed_kinds(self.t.p)).get(url)
            return by_kind[kind] if kind else b"<feed/>"  # the posted-check feeds
        return reddit.watch(self.t.p, dry_run=dry_run, pause=0, source="reddit", fetch=fetch)

    def test_a_fresh_invitation_is_an_app_lead(self):
        (r,) = self.run_feeds({"app": feed("SideProject", "Show off your app! What are you building this week?"),
                               "domain": b"<feed/>"})
        self.assertEqual(r["kind"], "app")
        self.assertIn("self-promotion rules", r["notes"])

    def test_an_app_lead_over_a_day_old_is_dropped(self):
        # The site-wide search keeps a day; the showcase subs' search keeps three.
        def fetch(url, pause, agent=None):
            if url in [reddit.search_url(q) for q in kinds.APP["site_searches"]]:
                return feed("SideProject", "Show off your app!", hours=30)
            return b"<feed/>"
        self.assertEqual(reddit.watch(self.t.p, dry_run=True, pause=0, source="reddit", fetch=fetch), [])

    def test_showcase_subs_are_searched_as_app_feeds(self):
        # r/buildinpublic and the other show-your-work subs run weekly threads,
        # searched as one multireddit for every product.
        urls = [u for u, k in reddit.feed_kinds(self.t.p) if k == "app"]
        multi = "+".join(kinds.APP["subreddits"])
        self.assertTrue(any(f"/r/{multi}/search.rss" in u for u in urls))
        self.assertIn("buildinpublic", kinds.APP["subreddits"])

    def test_a_weekly_showcase_thread_counts_for_three_days(self):
        def fetch(url, pause, agent=None):
            if "/r/" + "+".join(kinds.APP["subreddits"]) + "/search.rss" in url:
                return feed("buildinpublic", "Weekly thread: share what you're building this week", hours=60)
            return b"<feed/>"
        (r,) = reddit.watch(self.t.p, dry_run=True, pause=0, source="reddit", fetch=fetch)
        self.assertEqual(r["kind"], "app")

    def test_a_showcase_sub_thread_over_three_days_is_dropped(self):
        def fetch(url, pause, agent=None):
            if "/r/" + "+".join(kinds.APP["subreddits"]) + "/search.rss" in url:
                return feed("buildinpublic", "Weekly thread: share what you're building this week", hours=80)
            return b"<feed/>"
        self.assertEqual(reddit.watch(self.t.p, dry_run=True, pause=0, source="reddit", fetch=fetch), [])

    def test_someone_elses_launch_is_not_an_app_lead(self):
        rows = self.run_feeds({"app": feed("SideProject", "I built an app to share your app links, would you use it?"),
                               "domain": b"<feed/>"})
        self.assertEqual(rows, [])

    def test_a_domain_ask_is_a_domain_lead(self):
        (r,) = self.run_feeds({"app": b"<feed/>",
                               "domain": feed("climbing", "Plateaued at V4, need a training plan",
                                              "Not improving for a year.", hours=60)})
        self.assertEqual(r["kind"], "domain")

    def test_kind_is_added_to_an_older_tsv(self):
        old = [f for f in reddit.FIELDS if f != "kind"]
        self.t.write("Reddit", [{"url": "https://www.reddit.com/r/a/comments/old1/", "status": "skip"}], old)
        self.run_feeds({"app": feed("SideProject", "Show off your app!"), "domain": b"<feed/>"}, dry_run=False)
        fields, rows = tsv.read(self.t.p.reddit_tsv)
        self.assertIn("kind", fields)
        self.assertEqual([r["kind"] for r in rows], ["", "app"])


class TallyTest(unittest.TestCase):
    def test_counts_by_kind_with_blank_as_domain(self):
        rows = [{"kind": "app", "status": "posted"}, {"kind": "", "status": "posted"},
                {"kind": "domain", "status": "skip"}, {"status": "draft"}]
        self.assertEqual(kinds.tally(rows), {"app": {"posted": 1}, "domain": {"posted": 1, "skip": 1, "draft": 1}})


class DraftCardTest(unittest.TestCase):
    def row(self, kind):
        return {"product": "cragbook", "app": "Cragbook", "platform": "Reddit", "where": "r/x", "url": "u",
                "reply_text": "hi", "kind": kind}

    def test_app_drafts_are_labelled(self):
        self.assertIn("app thread", drafts.card(self.row("app"), ["cragbook"]))

    def test_domain_drafts_are_not(self):
        self.assertNotIn("app thread", drafts.card(self.row(""), ["cragbook"]))


if __name__ == "__main__":
    unittest.main()
