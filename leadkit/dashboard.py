"""The analytics dashboard: one local page with every app's App Store numbers and posts.

`leads dashboard` reads the saved analytics files (analytics.py), `marketing/sales.tsv`
and `marketing/posts.tsv`, writes one self-contained HTML file with the data inside it,
and opens it in Chrome. No server: reopen the file any time, and run
`leads dashboard --sync` to pull Apple's newest files first.

Per app it shows impressions, product page views, first-time downloads (by source),
units sold, and the conversion rate, with every post drawn on the timeline so a spike
can be read against what went out that day. The post table gives each day's lift:
page views on its day and the day after, against the median day of the week before.

Posts are posts.tsv's videos and posts, plus each app's posted replies from its leads
files (Reddit, Threads, X) and its own Reddit posts (leads/reddit-posts.tsv), each with
a type (Short, Reel, Reddit reply...) so a day can be read by what kind of thing went out.
"""
import http.server, json, os, re, statistics, subprocess, sys, threading, time, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import analytics, aso, eastern, insights, live, mlog, posts as reddit_posts, product, ratings, stats, tsv

TEMPLATE = Path(__file__).parent / "data" / "dashboard.html"
OUT = Path.home() / "Library" / "Caches" / "leadkit" / "dashboard.html"
# The four sources worth a colour; the rest fold into Other.
SOURCES = ("App Store search", "App Store browse", "Web referrer", "App referrer")


def source_of(s):
    return s if s in SOURCES else "Other"


def post_type(channel, url=""):
    """What kind of post a posts.tsv row is, from its channel and link."""
    c, u = (channel or "").lower(), (url or "").lower()
    if "youtu" in c or "youtu" in u:
        return "Short" if "/shorts/" in u or not u else "YouTube video"
    if "instagram" in c or "instagram.com" in u:
        return "Reel"
    if "tiktok" in c:
        return "TikTok"
    if c.startswith("threads"):
        return "Threads post"
    if c.startswith("reddit"):
        return "Reddit post"
    if c == "x" or c.startswith("x "):
        return "X post"
    if "product hunt" in c or "director" in c:
        return "Launch"
    return channel or "Other"


def replies(leads):
    """Posted replies from a product's leads rows, {"reddit"|"threads"|"x": rows}, oldest first.
    A posted row with no posted date takes the day it was found (`about`: "found")."""
    out = []
    for site, rows in leads.items():
        for r in rows or []:
            if stats.outcome(r) != "posted":
                continue
            day = (r.get("posted") or "").strip()[:10]
            about = ""
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
                day, about = (r.get("found") or "").strip()[:10], "found"
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
                continue
            sub = (r.get("subreddit") or "").strip()
            who = (r.get("author") or "").strip().lstrip("@")
            out.append({"date": day, "type": {"reddit": "Reddit reply", "threads": "Threads reply", "x": "X reply"}[site],
                        "channel": f"r/{sub}" if site == "reddit" and sub else site.capitalize() if site != "x" else "X",
                        "title": (r.get("title") or "").strip() or (f"@{who}" if who else ""),
                        "url": (r.get("url") or "").strip(), "about": about,
                        "mentions": "app" if (r.get("kind") or "").strip() == "app" else ""})
    return sorted(out, key=lambda r: r["date"])


def own_reddit(rows):
    """The app's own Reddit posts (leads/reddit-posts.tsv) as posts, score as likes."""
    return [{"date": r["posted"][:10], "type": "Reddit post", "channel": f"r/{r.get('sub', '')}",
             "title": r.get("title", ""), "url": r.get("url", ""), "likes": r.get("score", ""),
             "replies": r.get("comments", "")} for r in rows if r.get("posted")]


def extra_posts(name):
    """Replies and own Reddit posts for the app called `name`, from its product folder."""
    p = next((p for p in product.everything() if p.title == name), None)
    if not p:
        return []
    leads = {site: tsv.read(p.leads / f"{site}-leads.tsv")[1] for site in ("reddit", "threads", "x")}
    return replies(leads) + own_reddit(reddit_posts.read(p))


POST_KEYS = ("date", "type", "channel", "ref", "title", "url", "views", "likes", "replies", "about", "mentions")


def app_data(app_id, title, apps, sales, posts, raw=None, extra=()):
    """One app's series, keyed by date, for the page."""
    name = mlog.app_of(title, apps)
    days = defaultdict(lambda: defaultdict(int))
    countries = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for (d, metric, src, terr), (c, u) in analytics.rows(app_id, raw).items():
        if metric == "page_views":
            days[d]["page_views"] += u
        elif metric == "impressions":
            days[d]["impressions"] += u
        else:
            days[d][metric] += c
        if metric == "downloads":
            days[d]["dl:" + source_of(src)] += c
        if metric == "page_views":
            days[d]["pv:" + source_of(src)] += u
        countries[d][terr][metric] += u if metric in ("page_views", "impressions") else c
    for r in sales:
        if r["app"] == name:
            days[r["date"]]["units_" + r["store"].lower()] += int(r["units"] or 0)
            days[r["date"]]["proceeds"] += float(r.get("proceeds") or 0)
    own = [p | {"type": post_type(p.get("channel"), p.get("url")), "title": p.get("note", "")}
           for p in posts if p["app"] == name]
    logged = {p.get("url") for p in own if p.get("url")}
    own += [x for x in extra if not x.get("url") or x["url"] not in logged]
    for p in own:
        days[p["date"]]  # a post day exists on the axis even with no numbers
    return {
        "id": app_id, "name": name, "title": title,
        "days": {d: dict(v) for d, v in sorted(days.items())},
        "countries": {d: {t: dict(m) for t, m in v.items()} for d, v in sorted(countries.items())},
        "posts": [{k: p.get(k, "") or "" for k in POST_KEYS} for p in sorted(own, key=lambda p: p["date"])],
    }


def lift(days, day, metric="page_views", before=7):
    """(page views on the day and the next, median of two such days in the week before)."""
    d0 = date.fromisoformat(day)
    def get(d):
        return days.get(d.isoformat(), {}).get(metric, 0)
    after = get(d0) + get(d0 + timedelta(1))
    base = [get(d0 - timedelta(i)) for i in range(1, before + 1)]
    return after, 2 * statistics.median(base)


def projection(values, horizon=92, weeks=3, trend_days=56, carry=14):
    """A forecast for the days after `values` (one total per day, oldest first, no gaps).

    The level is the middle of the last `weeks` weekly totals, a seventh of it per day, so
    one launch spike or one dead week doesn't set it. On that goes the trend: the median
    slope between every pair of the last `trend_days` days (Theil-Sen, which one big day
    barely moves), for `carry` days and then held flat. Never below 0. `sd` is the daily
    swing over the last four weeks: a period of n days is roughly ±1.28·sd·√n (80%)."""
    if len(values) < 7:
        return {"days": [], "sd": 0}
    totals = [sum(values[len(values) - 7 * (w + 1):len(values) - 7 * w]) for w in range(weeks)
              if len(values) >= 7 * (w + 1)]
    level = statistics.median(totals) / 7
    tail = values[-trend_days:]
    slopes = [(tail[j] - tail[i]) / (j - i) for i in range(len(tail)) for j in range(i + 1, len(tail))]
    slope = statistics.median(slopes) if slopes else 0
    days = [max(0.0, level + slope * min(k, carry)) for k in range(1, horizon + 1)]
    last = values[-28:]
    sd = statistics.pstdev(last) if len(last) > 1 else 0
    return {"days": [round(v, 3) for v in days], "sd": round(sd, 3)}


def sales_projection(sales, through):
    """projection() for proceeds, customer sales and units across every app, from the first sale to `through`."""
    if not sales or not through:
        return None
    per = defaultdict(lambda: [0, 0.0, 0.0])
    for r in sales:
        per[r["date"]][0] += int(r["units"] or 0)
        per[r["date"]][1] += float(r.get("proceeds") or 0)
        per[r["date"]][2] += float(r.get("sales") or 0)
    d, end, units, dollars, paid = date.fromisoformat(min(per)), date.fromisoformat(through), [], [], []
    while d <= end:
        u, p, s = per.get(d.isoformat(), (0, 0.0, 0.0))
        units.append(u)
        dollars.append(p)
        paid.append(s)
        d += timedelta(1)
    return {"from": (end + timedelta(1)).isoformat(), "u": projection(units), "p": projection(dollars),
            "s": projection(paid)}


def store_projections(sales, through):
    """sales_projection() for both stores together, with each store's own under "stores".
    The level is a median, so the stores' forecasts don't add up to the combined one."""
    both = sales_projection(sales, through)
    if both:
        both["stores"] = {s: sales_projection([r for r in sales if r["store"] == s], through) for s in ("iOS", "Play")}
    return both


def waiting(app_list, shown, apps):
    """Leadkit's apps that Apple hasn't sent an analytics report for yet (a new app on its
    launch day), so the page can list them before their first numbers arrive."""
    out = []
    for app_id, title in app_list:
        name = mlog.app_of(title, apps)
        if app_id not in shown and name in apps:
            out.append({"id": app_id, "name": name, "title": title})
    return out


def build(app_list=None, raw=None):
    apps = [p.title for p in product.everything()]
    sales = mlog._read(mlog.SALES, mlog.SALES_FIELDS)
    posts = mlog._read(mlog.POSTS, mlog.POST_FIELDS)
    # The Sales tab is in Eastern days; each app's own page keeps the stores' days, like Apple's analytics.
    saved = eastern.load()
    through = eastern.through(sales, saved["fetched"])
    by_day = eastern.rows(sales, saved["rows"], through)
    out = []
    app_list = app_list or analytics.apps()
    for app_id, title in app_list:
        a = app_data(app_id, title, apps, sales, posts, raw, extra_posts(mlog.app_of(title, apps)))
        if not any(k for v in a["days"].values() for k in v):
            continue
        for p in a["posts"]:
            p["after"], p["base"] = lift(a["days"], p["date"])
        a["works"] = insights.what_works([a])
        a["insights"] = insights.insights(a, a["works"])
        out.append(a)
    out.sort(key=lambda a: -sum(v.get("downloads", 0) for v in a["days"].values()))
    return {"built": date.today().isoformat(), "synced": last_synced(), "apps": out,
            "waiting": waiting(app_list, {a["id"] for a in out}, apps), "works": insights.what_works(out), "sources": list(SOURCES) + ["Other"],
            "ratings": ratings.load(),  # the saved copy; the served page asks /ratings for a fresh one
            # Each product's newest App Store search ranks (the Keywords tab).
            "ranks": [{"app": p.title, **r} for p in product.everything() for r in aso.rankings(p)],
            "sales_through": through,
            "eastern_from": eastern.first_day(saved["rows"]),
            "projection": store_projections(by_day, through),
            # Every app's sales, including ones with no analytics yet (the Sales tab).
            "sales": [{"d": r["date"], "app": r["app"], "store": r["store"], "u": int(r["units"] or 0),
                       "p": float(r.get("proceeds") or 0), "s": float(r.get("sales") or 0)} for r in by_day]}


def sync_commit():
    """When the newest daily sync commit was made (ISO), or ""."""
    try:
        return subprocess.run(["git", "log", "-1", "--format=%cI", "--grep=^analytics: daily sync"],
                              cwd=product.DATA, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def last_synced(stamp=None, raw=None, commit=sync_commit):
    """When the last sync finished, as UTC ISO: the newest of the stamp a sync leaves, the
    newest daily sync commit, and the newest file a sync downloaded. The Sync button
    commits nothing, so before the stamp existed the commit alone ran hours behind."""
    stamp = analytics.LAST_SYNC if stamp is None else stamp
    raw = analytics.RAW if raw is None else raw
    times = []
    for iso in (analytics.last_sync(stamp), commit()):
        try:
            times.append(datetime.fromisoformat(iso.replace("Z", "+00:00")))
        except ValueError:
            pass
    newest = max((f.stat().st_mtime for f in raw.glob("*/*/*.gz")), default=None) if raw.is_dir() else None
    if newest is not None:
        times.append(datetime.fromtimestamp(newest, timezone.utc))
    return max(times).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if times else ""


def render(data):
    return TEMPLATE.read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))


PORT = 8418
IDLE_MINUTES = 20  # the page pings every minute; no ping this long means the tab is closed


def running(port=PORT):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=2) as r:
            return r.read() == b"leadkit-dashboard"
    except OSError:
        return False


def changed_since(started, root=None):
    """Code files (leadkit/*.py and the page) modified after the server started, relative
    to the repo. A server left running serves the old code."""
    root = Path(root or product.HOME)
    files = sorted((root / "leadkit").glob("*.py")) + [root / "leadkit" / "data" / "dashboard.html"]
    return [str(f.relative_to(root)) for f in files if f.is_file() and f.stat().st_mtime > started]


def restart_command(port=PORT):
    """What the Restart button runs in place of the server: the same Python, freshly
    imported code, the same port, and no new Chrome tab."""
    return [sys.executable, "-m", "leadkit.cli", "dashboard", "--no-open", "--port", str(port)]


def serve(port=PORT, open_browser=True, log=print):
    """Serve the page on 127.0.0.1 until no page has pinged it for IDLE_MINUTES.
    If one is already up, only open the page."""
    url = f"http://127.0.0.1:{port}/"
    if running(port):
        log(f"already running: {url}")
        if open_browser:
            subprocess.run(["open", "-a", "Google Chrome", url])
        return
    job = analytics.Job()
    known = []
    started = time.time()

    def app_list():
        if not known:
            known.extend(analytics.apps())
        return known
    seen = {"at": time.time()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            seen["at"] = time.time()
            path = self.path.split("?")[0]
            if path == "/":
                return self.send(200, render(build()), "text/html")
            if path == "/ping":
                return self.send(200, "leadkit-dashboard", "text/plain")
            if path == "/live":
                return self.send(200, json.dumps(live.cached()))
            if path == "/ratings":
                return self.send(200, json.dumps(ratings.cached(app_list())))
            if path == "/sync":
                return self.send(200, json.dumps(job.state()))
            if path == "/version":
                return self.send(200, json.dumps({"changed": changed_since(started)}))
            self.send(404, "{}")

        def do_POST(self):
            seen["at"] = time.time()
            # Only the page itself may start a sync (another site can't POST here with this header).
            if self.path == "/sync" and self.headers.get("X-Leadkit") == "1":
                job.start()
                return self.send(200, json.dumps(job.state()))
            if self.path == "/restart" and self.headers.get("X-Leadkit") == "1":
                # Not mid-sync: the new process would lose it. Otherwise answer, then replace
                # this process with a fresh one so code changes since it started take effect.
                if job.running:
                    return self.send(409, json.dumps({"error": "a sync is running"}))
                self.send(200, json.dumps({"restarting": True}))
                threading.Thread(target=restart, daemon=True).start()
                return
            self.send(403, "{}")

        def log_message(self, *a):
            pass

    def restart():
        time.sleep(0.3)  # let the answer reach the page
        server.shutdown()
        server.server_close()
        os.chdir(product.HOME)
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(product.HOME), os.environ.get("PYTHONPATH", "")]))
        cmd = restart_command(port)
        os.execv(cmd[0], cmd)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(url)
    if open_browser:
        subprocess.run(["open", "-a", "Google Chrome", url])
    while time.time() - seen["at"] < IDLE_MINUTES * 60 or job.running:
        time.sleep(15)
    server.shutdown()
    log("closed")


def write_file(path=OUT):
    """The page as a file, with no Sync button or live view behind it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(build()))
    return path
