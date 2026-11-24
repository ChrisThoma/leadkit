"""leads: the leads pass tools for every product.

Run inside an app repo and the product is picked from it; pass -p/--product
anywhere else. `leads drafts --all` puts every product's drafts on one page.

    leads drafts                     # serve the drafts page in Chrome, sync when the tab closes
    leads drafts --all               # every product on one page
    leads drafts --no-open           # write the page to a file and print where
    leads drafts --keep              # sync on every close and keep serving
    leads looking "Reading r/Baking threads"  # the drafts page shows it's still looking (20 min)
    leads looking --done             # the pass has finished looking
    leads reddit                     # mark posted, then find new Reddit leads
    leads reddit --dry-run           # print matches and near misses, append nothing
    leads reddit --posted-only       # only mark replied threads as posted
    leads reddit --source reddit     # read Reddit's own feeds (default: Arctic Shift listings)
    leads thread URL [URL ...]       # read a Reddit thread and its comments (Arctic Shift)
    leads comments [--dry-run]       # threads where a recent comment used a COMMENT_PHRASES phrase
    leads comments --hourly          # install the hourly job (triage headless, banner drafts); --off removes it
    leads reddit-eval [-v]           # score every post you've judged
    leads threads-searches [group]   # the Threads search URLs for Chrome
    leads kinds                      # drafted, posted and skipped leads per kind
    leads stats [--all] [--since DATE]   # the funnel: found, drafted, posted by sub, score and week
    leads threads-yield [--all] [--since DATE] [--min-views 50]   # which searches found leads whose replies got views
    leads posts [--all] [--offline]  # ad subs: own posts' scores, when each sub takes the next ad
    leads set URL status=skip notes+="gear question"   # change one lead row (reply=- reads stdin)
    leads set URL --add kind=domain notes="From F5Bot"  # log a thread that isn't in the file yet
    leads set URL query="drop your app"   # record which search found a Threads or X lead
    leads threads-searches --js | --replies-js | --attach-js
    leads threads-posted [URL ...]   # mark Threads rows posted (or pairs on stdin)
    leads threads-api [--dry-run]    # the official keyword_search watcher (needs a token)
    leads threads-login [REDIRECT]   # sign in to Threads for a token with every scope
    leads threads                    # the Threads page: search, mentions, our posts, new post
    leads threads-insights           # log views and likes per recent post to threads-insights.tsv
    leads threads-insights --daily [--at 09:20]   # install the daily launchd log; --off removes it
    leads x-post [THREADS_URL]       # our latest Threads post (or that one) as X posts, ct=x links, media saved
    leads x-searches [group]         # the X search URLs for Chrome (X_SEARCHES, else the Threads searches)
    leads x-searches --js            # the extractor to run in an X search tab
    leads x-posted URL [OUR_REPLY]   # mark an X row posted (or pairs on stdin)
    leads x-insights [--daily]       # log our X posts' views (X API, pay-per-use); --daily installs the job
    leads threads-post "TEXT"        # publish a post as your Threads account (asks first)
    leads study reddit [--days 30]   # what does well in the product's subs: report in study/
    leads study threads-urls         # the product's Threads searches on the Top tab
    leads study threads-js           # extractor to run on each of those pages (gathers in the tab)
    leads study threads-receive      # saves what the tab gathered (prints the script to run there), then reports
    leads study threads [FILE ...]   # add extractor output, report on everything gathered
    leads pitches [--todo 3]         # roundups, lists, creators: follow-ups due, awaiting a reply, next to pitch
    leads pitches add URL target="Example Blog" kind=roundup route=... fit=...   # a new target (status todo)
    leads pitches set URL status=sent code=ABC123   # sent fills today and a follow-up in 7 days; notes+= appends
    leads products                   # list products and where their leads live
    leads log sync [--days 14]       # every app's sales and posts into marketing/ (the Monday review)
    leads log week [--since DATE]    # units, posts and posts not read back, per app, for a week
    leads log day [--since DATE]     # one day's sales and posts as JSON, for the daily recap (default yesterday)
    leads analytics sync             # Apple's new analytics files, then sales and posts (leads log sync)
    leads analytics daily [--at 03:00] [--off]   # install the 3 a.m. sync job (commits, no push)
    leads dashboard                  # the analytics page on 127.0.0.1:8418: Live, Sync, every app
    leads log set URL views=N likes=N [--add app=X channel=Y]   # numbers read by hand (Reels, TikTok)
    leads setup [--check] [--new NAME]   # set up this Mac or a new product, step by step
"""
import argparse, json, os, sys, tempfile
from datetime import date
from pathlib import Path

from . import analytics, arctic, comments, dashboard, drafts, kinds, looking, mlog, pitches, product, reddit, posts, rows, setup, stats, study, threads, threadsapi, tsv, x, yields


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Setup has its own parser, so bin/setup and `leads setup` take the same flags. It covers every
    # product, so a -p in front is dropped.
    rest = argv[2:] if argv[:1] in (["-p"], ["--product"]) else argv
    if rest[:1] == ["setup"]:
        return setup.main(rest[1:])
    ap = argparse.ArgumentParser(prog="leads", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--product", help="product name (default: the app repo you're in)")
    # -p works after the subcommand too (`leads reddit -p proofer`); SUPPRESS keeps one given before it.
    either = argparse.ArgumentParser(add_help=False)
    either.add_argument("-p", "--product", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser
    sub.add_parser = lambda *a, **k: add(*a, parents=[either], **k)

    d = sub.add_parser("drafts", help="the reply drafts page")
    d.add_argument("--all", action="store_true", help="every product on one page")
    d.add_argument("--no-open", action="store_true", help="write the page to a file instead of serving it")
    d.add_argument("--keep", action="store_true", help="keep serving after the tab closes")

    lk = sub.add_parser("looking", help="tell the open drafts page what the pass is still doing")
    lk.add_argument("what", nargs="?", help="a few words, shown on the page for 20 minutes unless renewed")
    lk.add_argument("--done", action="store_true", help="the pass has finished looking")

    r = sub.add_parser("reddit", help="find Reddit leads")
    r.add_argument("--days", type=int, default=7, help="ignore posts older than this")
    r.add_argument("--pause", type=float, help="seconds between requests (default: the product's)")
    r.add_argument("--dry-run", action="store_true", help="print matches, don't append")
    r.add_argument("--subreddits", nargs="*")
    r.add_argument("--min-score", type=int)
    r.add_argument("--posted-only", action="store_true", help="only mark replied threads as posted")
    r.add_argument("--source", choices=["arctic", "reddit"], default="arctic",
                   help="arctic: list each sub through Arctic Shift, search locally (default); "
                        "reddit: Reddit's feeds, about 30 s apart, no search since 2026-11-10")

    cm = sub.add_parser("comments", help="threads where a recent comment used one of the product's phrases")
    cm.add_argument("--hours", type=float, default=3, help="comments from the last this many hours")
    cm.add_argument("--dry-run", action="store_true", help="print, don't append")
    cm.add_argument("--scheduled", action="store_true", help="what the hourly job runs: find, triage, banner, commit")
    cm.add_argument("--hourly", action="store_true", help="install the hourly launchd job")
    cm.add_argument("--off", action="store_true", help="remove the hourly job")

    th = sub.add_parser("thread", help="read Reddit threads and their comments through Arctic Shift")
    th.add_argument("urls", nargs="+")

    e = sub.add_parser("reddit-eval", help="score the posts you've judged")
    e.add_argument("-v", action="store_true", help="every post with its score")

    t = sub.add_parser("threads-searches", help="Threads search URLs for Chrome")
    t.add_argument("groups", nargs="*")
    t.add_argument("--js", action="store_true", help="print the results extractor")
    t.add_argument("--replies-js", action="store_true", help="print the posted-replies reader")
    t.add_argument("--attach-js", action="store_true", help="print the media attach helper")

    m = sub.add_parser("threads-posted", help="mark Threads rows posted")
    m.add_argument("items", nargs="*", help="post URLs; with none, read 'parent reply' pairs from stdin")

    a = sub.add_parser("threads-api", help="Threads keyword_search watcher")
    a.add_argument("--days", type=int, default=3)
    a.add_argument("--pause", type=float, default=1.0)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--include-replies", action="store_true")
    a.add_argument("--min-score", type=int)
    a.add_argument("--refresh-token", action="store_true")

    g = sub.add_parser("threads-login", help="sign in to Threads and save a token")
    g.add_argument("redirect", nargs="?", help="the address Threads redirected to after approving")

    sub.add_parser("threads", help="the Threads page in Chrome")
    ti = sub.add_parser("threads-insights", help="log insights for recent posts")
    ti.add_argument("--daily", action="store_true", help="install the daily launchd job instead")
    ti.add_argument("--at", default="09:20", help="--daily: local time, HH:MM")
    ti.add_argument("--off", action="store_true", help="--daily: remove the job")
    ti.add_argument("--scheduled", action="store_true", help="what the job runs: refresh token, log, commit")
    xp = sub.add_parser("x-post", help="a Threads post as X posts")
    xp.add_argument("url", nargs="?", help="the Threads post (default: the latest)")
    xp.add_argument("--media-dir", default=str(Path(tempfile.gettempdir()) / "leadkit-x-post"),
                    help="where the post's video or image is saved")
    xs = sub.add_parser("x-searches", help="the X search URLs for Chrome")
    xs.add_argument("groups", nargs="*")
    xs.add_argument("--js", action="store_true", help="print the extractor instead")
    xd = sub.add_parser("x-posted", help="mark X rows posted")
    xd.add_argument("items", nargs="*", help="thread URL, optionally followed by our reply's URL")
    xi = sub.add_parser("x-insights", help="log our X posts' metrics")
    xi.add_argument("--daily", action="store_true", help="install the daily launchd job instead")
    xi.add_argument("--at", default="09:25", help="--daily: local time, HH:MM")
    xi.add_argument("--off", action="store_true", help="--daily: remove the job")
    xi.add_argument("--scheduled", action="store_true", help="what the job runs: log and commit")
    tp = sub.add_parser("threads-post", help="publish a post (asks first)")
    tp.add_argument("text")

    s = sub.add_parser("set", help="change or add one lead row (never edit a leads TSV by hand)")
    s.add_argument("url")
    s.add_argument("pairs", nargs="+", metavar="field=value",
                   help="field+=value appends; value - reads it from stdin, for multi-line replies")
    s.add_argument("--add", action="store_true", help="add a row if the thread isn't logged yet (needs kind=)")

    st = sub.add_parser("study", help="what other people post that does well (Reddit, Threads)")
    st.add_argument("what", choices=["reddit", "threads", "threads-urls", "threads-js", "threads-receive"])
    st.add_argument("files", nargs="*", help="threads: extractor output files to add")
    st.add_argument("--days", type=int, default=30, help="reddit: how far back to read")
    st.add_argument("--subreddits", nargs="*", help="reddit: these subs instead of the product's")
    st.add_argument("--no-label", action="store_true", help="skip naming each sampled post's hook with claude -p")

    sub.add_parser("kinds", help="leads per kind (app, domain) and status")
    po = sub.add_parser("posts", help="ad subs (POST_SUBS): own posts and when the next is allowed")
    po.add_argument("--all", action="store_true", help="every product")
    po.add_argument("--offline", action="store_true", help="read the log only, don't ask Arctic Shift")
    sa = sub.add_parser("stats", help="found, drafted and posted, by sub, score and week")
    sa.add_argument("--all", action="store_true", help="every product")
    sa.add_argument("--since", help="only leads found on or after this date (YYYY-MM-DD)")
    sa.add_argument("--min-found", type=int, default=10, help="list subs with at least this many leads")
    ty = sub.add_parser("threads-yield", help="views of our replies, by the search that found the lead")
    ty.add_argument("--all", action="store_true", help="every product")
    ty.add_argument("--since", help="only leads found on or after this date (YYYY-MM-DD)")
    ty.add_argument("--min-views", type=int, default=50, help="count replies that reached this many views")
    sub.add_parser("products", help="list products")
    pi = sub.add_parser("pitches", help="roundups, lists and creators to pitch, and the follow-ups due")
    pi.add_argument("items", nargs="*", metavar="add|set URL field=value",
                    help="add URL field=value ... or set URL field=value ... (field+=value appends)")
    pi.add_argument("--todo", type=int, default=3, help="how many targets to list as next")
    an = sub.add_parser("analytics", help="App Store analytics files from Apple, for every app")
    an.add_argument("what", choices=["sync", "daily"])
    an.add_argument("--scheduled", action="store_true", help="what the 3 a.m. job runs: sync everything, commit")
    an.add_argument("--at", default="03:00", help="daily: the time (the Mac's clock, Eastern)")
    an.add_argument("--off", action="store_true", help="daily: remove the job")
    db = sub.add_parser("dashboard", help="the analytics page in Chrome")
    db.add_argument("--no-open", action="store_true", help="serve the page without opening Chrome")
    db.add_argument("--file", action="store_true", help="write the page to a file instead (no Sync, no live view)")
    db.add_argument("--port", type=int, default=dashboard.PORT, help="serve on this port (default 8418)")
    lg = sub.add_parser("log", help="the cross-app marketing log: sales and posts")
    lg.add_argument("what", choices=["sync", "week", "day", "set"])
    lg.add_argument("items", nargs="*", help="set: URL then field=value pairs")
    lg.add_argument("--days", type=int, default=14, help="sync: how many days of sales to pull")
    lg.add_argument("--since", help="week: the Monday to start from (default: the last full week); day: the day (default yesterday)")
    lg.add_argument("--add", action="store_true", help="set: add the post if it isn't logged")
    sub.add_parser("setup", help="set up this Mac or a new product (leads setup --help)")

    args = ap.parse_args(argv)

    if args.cmd == "threads-insights":  # one account for every product, so no product needed
        if args.daily or args.off:
            return threads.install_insights_job(args.at, args.off)
        if args.scheduled:
            return threads.scheduled_insights()
        tok = threads.token()
        for r in threads.log_insights(tok, threads.INSIGHTS_TSV):
            print(f"{r['posted']}  {r['views']:>6} views {r['likes']:>4} likes  {r['text']}")
        fresh = threads.log_reply_insights(tok, threads.REPLIES_TSV)
        print(f"replies: {len(fresh)} refreshed, {len(tsv.read(threads.REPLIES_TSV)[1])} in {threads.REPLIES_TSV.name}")
        return
    if args.cmd == "x-post":  # one account for every product, so no product needed
        return x.print_crosspost(threads.token(), args.url, args.media_dir)
    if args.cmd == "x-insights":
        if args.daily or args.off:
            return x.install_insights_job(args.at, args.off)
        if args.scheduled:
            return x.scheduled_insights()
        for r in x.log_insights(x.token(), x.INSIGHTS_TSV):
            print(f"{r['posted']}  {r['views']:>6} views {r['likes']:>4} likes  {r['text']}")
        return
    if args.cmd == "x-searches" and args.js:
        return print(x.EXTRACT_JS)
    if args.cmd == "analytics":  # every app on the account
        if args.what == "daily":
            print(analytics.install_job(args.at, args.off))
        elif args.scheduled:
            analytics.scheduled()
        else:
            analytics.sync_everything()
        return 0
    if args.cmd == "dashboard":
        if args.file:
            print(dashboard.write_file())
        else:
            dashboard.serve(port=args.port, open_browser=not args.no_open)
        return 0
    if args.cmd == "log":  # every product at once, so no product needed
        if args.what == "sync":
            print("\n".join(mlog.sync(args.days)))
        elif args.what == "week":
            print(mlog.week(args.since))
        elif args.what == "day":  # JSON for the daily recap: --since names the day (default yesterday)
            print(json.dumps(mlog.day(args.since), indent=1))
        else:
            if not args.items:
                raise SystemExit("leads log set URL field=value ...")
            print(mlog.set_post(args.items[0], args.items[1:], args.add))
        return 0
    if args.cmd == "pitches":
        today = date.today()
        if args.items:
            what, url, pairs = args.items[0], args.items[1:2], args.items[2:]
            if what not in ("add", "set") or not url:
                raise SystemExit("leads pitches [add|set URL field=value ...]")
            p = product.pick(args.product)
            if what == "add":
                pitches.add(p, url[0], rows.parse(pairs))
            else:
                pitches.set_row(p, url[0], rows.parse(pairs), today)
            return
        # Like `leads log`: one product inside its repo or with -p, every product elsewhere.
        here = product.pick(args.product) if args.product else product.from_cwd()
        found = [t for t in (pitches.report(q, today, args.todo) for q in ([here] if here else product.everything())) if t]
        return print("\n\n".join(found) or "no products/<name>/pitches.tsv yet")
    if args.cmd == "comments":
        p = product.pick(args.product)
        if args.hourly or args.off:
            return comments.install_job(p, args.off)
        if args.scheduled:
            return comments.scheduled(p, hours=args.hours)
        return comments.run(p, dry_run=args.dry_run, hours=args.hours) and None
    if args.cmd == "products":
        for p in product.everything():
            print(f"{p.name:10} {p.title:10} {p.repo}  leads: {p.leads}")
        return
    if args.cmd == "drafts":
        products = product.everything() if args.all else [product.pick(args.product)]
        # Check lengths before a tab opens. If the warning only shows on the page,
        # fixing the reply means closing that page and opening another.
        too_long = [r for r in drafts.load(products)
                    if any("over Threads'" in w for w in r["warnings"])]
        for r in too_long:
            print(f"too long: {r['app']}: {r['url']}: {len(r['reply_text'])} characters, "
                  f"over Threads' {drafts.THREADS_LIMIT}")
        if args.no_open:
            return drafts.write_file(products)
        if too_long:
            raise SystemExit("shorten those replies (leads set <url> reply=-) before opening the page")
        return drafts.serve(products, keep=args.keep)
    if args.cmd == "posts":
        products = product.everything() if args.all else [product.pick(args.product)]
        found = None if args.offline else posts.fetch_own()
        return print("\n\n".join(posts.report(p, fetch=None if args.offline else (lambda: found)) for p in products))
    if args.cmd == "stats":
        products = product.everything() if args.all else [product.pick(args.product)]
        return print(stats.report(products, since=args.since, min_found=args.min_found))
    if args.cmd == "threads-yield":
        products = product.everything() if args.all else [product.pick(args.product)]
        return print(yields.report(products, threads.REPLIES_TSV, since=args.since, min_views=args.min_views,
                                   universe=product.everything()))
    if args.cmd == "thread":
        for i, url in enumerate(args.urls):
            if i:
                print("\n" + "=" * 72 + "\n")
            try:
                arctic.show_thread(url)
            except arctic.Error as err:
                print(f"{url}: {err}", file=sys.stderr)
        return
    if args.cmd == "threads-searches" and (args.js or args.replies_js):
        return print(threads.EXTRACT_JS if args.js else threads.replies_js())

    if args.cmd == "study" and args.what == "threads-js":
        return print(study.EXTRACT_JS)

    p = product.pick(args.product)
    if args.cmd == "study":
        if args.what == "threads-urls":
            for group, url in study.top_tab_urls(p):
                print(f"{group}\t{url}")
            return
        if args.what == "threads-receive":
            path = study.receive(p)
            if not path:
                raise SystemExit("nothing received")
            args.files = [str(path)]
            args.what = "threads"
        md = (study.study_reddit(p, days=args.days, subs=args.subreddits, labels=not args.no_label)
              if args.what == "reddit" else study.study_threads(p, args.files, labels=not args.no_label))
        return print(md)
    if args.cmd == "looking":
        if args.done or not args.what:
            looking.stop(p, "session")
            if not args.done:
                raise SystemExit("say what the pass is doing, or --done")
        else:
            looking.start(p, "session", args.what)
        return
    if args.cmd == "reddit":
        # The open drafts page shows the watcher as still looking while it runs.
        if not args.dry_run:
            looking.start(p, "reddit", "Reddit watcher", pid=os.getpid())
        try:
            reddit.watch(p, days=args.days, pause=args.pause, dry_run=args.dry_run, subreddits=args.subreddits,
                         min_score=args.min_score, posted_only=args.posted_only, source=args.source)
        finally:
            if not args.dry_run:
                looking.stop(p, "reddit")
    elif args.cmd == "set":
        rows.set_row(p, args.url, rows.parse(args.pairs), add=args.add)
    elif args.cmd == "kinds":
        kinds.report(p)
    elif args.cmd == "reddit-eval":
        reddit.evaluate(p, verbose=args.v)
    elif args.cmd == "threads-searches":
        if args.attach_js:
            print(threads.ATTACH_JS)
            files = threads.media(p)
            print(f"# then file_upload: {' or '.join(str(f) for f in files.values()) or '(no THREADS_MEDIA for ' + p.name + ')'}")
        else:
            threads.searches(p, args.groups)
    elif args.cmd == "threads-posted":
        threads.mark_posted(p, args.items or [line for line in sys.stdin if line.strip()])
    elif args.cmd == "x-searches":
        x.searches(p, args.groups)
    elif args.cmd == "x-posted":
        x.mark_posted(p, args.items or [line for line in sys.stdin if line.strip()])
    elif args.cmd == "threads-api":
        threads.api_watch(p, days=args.days, pause=args.pause, dry_run=args.dry_run,
                          include_replies=args.include_replies, min_score=args.min_score,
                          refresh_token=args.refresh_token)
    elif args.cmd == "threads-login":
        threads.login(p, args.redirect)
    elif args.cmd == "threads":
        drafts.serve([p], page="threads")
    elif args.cmd == "threads-post":
        print(args.text)
        if input(f"publish this as @{product.settings.THREADS_ACCOUNT}? [y/N] ").strip().lower() == "y":
            print(threadsapi.publish(threads.token(p), args.text)["permalink"])


if __name__ == "__main__":
    main()
