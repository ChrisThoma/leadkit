"""The marketing log: every app's posts and sales in one place, for the Monday review.

With units in `asc-sales` and `play-sales` and posts spread over per-app files,
experiments get logged as "Pending" and never read back, so nobody can say which
posts sold anything. This puts them side by side.

Two files in your data folder's `marketing/`:
- `sales.tsv`: units per day, app and store (iOS from asc-sales, Play from play-sales).
- `posts.tsv`: one row per post: the date, app, channel, link and numbers.

`leads log sync` refreshes both: sales for the last N days, Threads posts from
threads-insights.tsv, every app's experiments.tsv, and each app's own Reddit posts
(leads/reddit-posts.tsv, refreshed from Arctic Shift). `leads log set URL views=…`
records numbers by hand (Instagram, TikTok). YouTube views come from yt-dlp and
Reddit scores from Arctic Shift on each sync. `leads log week`
prints the review table.

Retention is read in Chrome, signed in, and recorded with `leads log set`:
- `stayed`: YouTube's "Stayed to watch", the percent of people shown a Short in the
  feed who didn't swipe away.
- `watched`: YouTube's "Average percentage viewed". It passes 100 when a Short loops.
Both are columns in Studio's advanced mode (Insights > Content > See more, with the
metrics Average percentage viewed and Stayed to watch), one table for every video.
Instagram's web insights (`insights_url`) give a Reel's views, likes and comments
but no watch time; that is only in the phone app.
"""
import re, shutil, subprocess
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from . import product, tsv

DIR = product.DATA / "marketing"
SALES = DIR / "sales.tsv"
POSTS = DIR / "posts.tsv"
# proceeds: dollars after the store's cut; sales: dollars the customers paid
SALES_FIELDS = ["date", "app", "store", "units", "proceeds", "sales"]
POST_FIELDS = ["date", "app", "channel", "ref", "url", "views", "likes", "replies", "stayed", "watched",
               "result", "note", "source"]
NUMBERS = ("views", "likes", "replies")
READ_RE = re.compile(r"\d[\d,.]*\s*[Kk]?\s*(views|upvotes|points|units|purchases|plays|likes|installs)\b")


def app_of(title, apps):
    """A store title to one app name: localized titles ("Proofer: temporizador de masa")
    share the part before the colon."""
    head = title.split(":")[0].strip()
    for a in apps:
        if head.lower().startswith(a.lower()):
            return a
    return head


def app_in(text, apps):
    """The first app a post names, or "" (a tooling post, or one about the account)."""
    low = (text or "").lower()
    hits = [(low.find(a.lower()), a) for a in apps if a.lower() in low]
    return min(hits)[1] if hits else ""


def parse_sales(text, store, apps):
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    head = lines[0].split("\t")
    total = defaultdict(lambda: [0, 0.0, 0.0])
    for line in lines[1:]:
        r = dict(zip(head, line.split("\t")))
        try:
            n = int(r.get("units") or 0)
            usd = float(r.get("proceeds") or 0)
            paid = float(r.get("sales") or 0)
        except ValueError:
            continue
        if n and re.match(r"\d{4}-\d\d-\d\d$", r.get("date", "")):
            t = total[(r["date"], app_of(r.get("title", ""), apps))]
            t[0] += n
            t[1] += usd
            t[2] += paid
    return [{"date": d, "app": a, "store": store, "units": str(n), "proceeds": f"{usd:.2f}",
             "sales": f"{paid:.2f}"} for (d, a), (n, usd, paid) in sorted(total.items())]


def merge_sales(old, new, start, stores=None):
    """Replace the pulled window (start onward) for the stores that were pulled."""
    pulled = set(stores) if stores is not None else None
    keep = [r for r in old if r["date"] < start or (pulled is not None and r["store"] not in pulled)]
    return sorted(keep + list(new), key=lambda r: (r["date"], r["app"], r["store"]))


def _blank(**kw):
    return dict.fromkeys(POST_FIELDS, "") | kw


def threads_posts(rows, apps):
    """Our Threads posts from threads-insights.tsv: the latest numbers for each URL."""
    latest = {}
    for r in rows:
        url = r.get("url", "")
        if url and (url not in latest or r.get("date", "") >= latest[url].get("date", "")):
            latest[url] = r
    return [_blank(date=r.get("posted", "")[:10], app=app_in(r.get("text", ""), apps), channel="Threads",
                   url=clean_url(url), views=r.get("views", ""), likes=r.get("likes", ""), replies=r.get("replies", ""),
                   note=(r.get("text") or "")[:80], source="threads-insights")
            for url, r in latest.items()]


URL_RE = re.compile(r"https?://[^\s;,)]+")
DOMAINS = [("youtu", "YouTube"), ("instagram.com", "Instagram"), ("threads.", "Threads"),
           ("tiktok.com", "TikTok"), ("x.com", "X"), ("twitter.com", "X"), ("reddit.com", "Reddit"),
           ("producthunt.com", "Product Hunt")]


def clean_url(u):
    return u.split("?")[0].split("#")[0].rstrip(".;,")


def channel_of(url):
    for needle, name in DOMAINS:
        if needle in url:
            if name == "Reddit":
                m = re.search(r"/r/(\w+)", url)
                return f"Reddit r/{m.group(1)}" if m else name
            return name
    return ""


SHORTCODE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def insights_url(url):
    """A Reel's insights page. Instagram addresses it by the media id, which is the
    link's shortcode read as a base-64 number."""
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:reel|p)/([\w-]+)", url or "")
    if not m:
        return ""
    n = 0
    for c in m.group(1):
        n = n * 64 + SHORTCODE.index(c)
    return f"https://www.instagram.com/insights/media/{n}/"


def experiment_posts(app, rows):
    """Experiments that went out (they have a publish date): one row per link, or one
    row with the logged channel when no link was recorded."""
    out = []
    for r in rows:
        m = re.search(r"\d{4}-\d\d-\d\d", r.get("publish_date") or "")
        if not m:
            continue
        base = _blank(date=m.group(), app=app, ref=r.get("id", ""),
                      result=(r.get("result") or "").strip()[:300],
                      note=(r.get("message") or "")[:80], source="experiments")
        urls = [clean_url(u) for u in URL_RE.findall(r.get("post_url") or "")]
        if urls:
            out += [base | {"url": u, "channel": channel_of(u) or r.get("channel", "")} for u in urls]
        else:
            out.append(base | {"channel": re.sub(r"\s*\(.*", "", (r.get("channel") or "").strip())})
    return out


def own_reddit_posts(app, rows):
    """The app's own Reddit posts (leads/reddit-posts.tsv) as posts, score as likes."""
    return [_blank(date=r.get("posted", ""), app=app, channel=f"Reddit r/{r.get('sub', '')}", url=r.get("url", ""),
                   likes=r.get("score", ""), replies=r.get("comments", ""), note=(r.get("title") or "")[:80],
                   source="reddit-posts")
            for r in rows if r.get("url")]


def refresh_own_reddit():
    """Log the account's new Reddit posts in each product's reddit-posts.tsv. Returns a
    line for the report when Arctic Shift couldn't be read."""
    from . import posts
    try:
        found = posts.fetch_own()
        for p in product.everything():
            posts.log(p, posts.mine(p, found))
    except Exception as e:
        return f"Reddit: own posts not refreshed, kept the old rows ({e})"
    return ""


def youtube_numbers(url):
    """Public views, likes and comments, through yt-dlp."""
    text, _ = _run(["yt-dlp", "--skip-download", "--no-warnings", "--print",
                    "%(view_count)s %(like_count)s %(comment_count)s", url], timeout=60)
    parts = (text or "").split()
    if len(parts) != 3:
        return None
    return tuple("" if x in ("NA", "None") else x for x in parts)


def reddit_numbers(url):
    """Score and comments from Arctic Shift (its copy can lag Reddit's)."""
    from . import arctic
    try:
        (p,) = arctic.get("posts/ids", {"ids": arctic.post_id(url), "fields": "score,num_comments"}) or [None]
    except Exception:
        return None
    return (str(p.get("score", "")), "", str(p.get("num_comments", ""))) if p else None


def read_numbers(posts, youtube=youtube_numbers, reddit=reddit_numbers):
    """Fill views, likes and replies for YouTube and Reddit posts. Returns the rows read."""
    got = []
    for r in posts:
        ch = r.get("channel", "")
        fetch = youtube if ch.startswith("YouTube") else reddit if ch.startswith("Reddit") else None
        if not fetch or not r.get("url"):
            continue
        nums = fetch(r["url"])
        if nums:
            if ch.startswith("YouTube"):
                r["views"], r["likes"], r["replies"] = nums
            else:
                r["likes"], r["replies"] = nums[0], nums[2]
            got.append(r)
    return got


REDDIT_ID = re.compile(r"reddit\.com/r/\w+/comments/(\w+)")


def _key(r):
    m = REDDIT_ID.search(r.get("url") or "")  # links come with and without the title slug
    if m:
        return ("reddit", m.group(1))
    return ("url", r["url"]) if r.get("url") else ("ref", r.get("app", ""), r.get("ref", ""), r.get("date", ""))


def merge_posts(old, new):
    """New values fill in and update a row; an empty new value never erases one."""
    rows = {_key(r): dict(r) for r in old}
    for r in new:
        k = _key(r)
        if k in rows:
            cur = rows[k]
            for f in POST_FIELDS:
                if f == "source" or (f == "url" and k[0] == "reddit"):
                    continue
                if r.get(f):
                    cur[f] = r[f]
        else:
            rows[k] = _blank() | r
    return sorted(rows.values(), key=lambda r: (r["date"], r["app"], r["channel"]))


def unread(r, today):
    """Out for two days or more with no numbers recorded."""
    if not r.get("date") or r["date"] > (date.fromisoformat(today) - timedelta(days=2)).isoformat():
        return False
    if any((r.get(f) or "").strip() for f in NUMBERS):
        return False
    return not READ_RE.search(r.get("result") or "")


def _units(sales, start, end):
    t = defaultdict(int)
    for r in sales:
        if start <= r["date"] <= end:
            t[r["app"]] += int(r["units"] or 0)
    return t


def week_report(sales, posts, start, end, today=None):
    today = today or date.today().isoformat()
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    span = (e - s).days + 1
    prev = ((s - timedelta(days=span)).isoformat(), (s - timedelta(days=1)).isoformat())
    now, before = _units(sales, start, end), _units(sales, *prev)
    week = [p for p in posts if start <= p["date"] <= end]
    apps = sorted(set(now) | set(before) | {p["app"] for p in week if p["app"]},
                  key=lambda a: (-now.get(a, 0), a))
    lines = [f"# Week {start} to {end}", "",
             "| App | Units | Week before | Posts | Threads views | Unread |",
             "|---|---|---|---|---|---|"]
    for a in apps + ([""] if any(not p["app"] for p in week) else []):
        mine = [p for p in week if p["app"] == a]
        tv = sum(int(p["views"]) for p in mine if p["channel"] == "Threads" and p["views"].isdigit())
        lines.append(f"| {a or '(no app named)'} | {now.get(a, 0) if a else ''} | {before.get(a, 0) if a else ''} "
                     f"| {len(mine)} | {tv} | {sum(unread(p, today) for p in mine)} |")
    by_channel = defaultdict(int)
    for p in week:
        by_channel[p["channel"] or "?"] += 1
    lines += ["", "Posts by channel: " + (", ".join(f"{c} {n}" for c, n in sorted(by_channel.items())) or "none")]
    todo = [p for p in posts if unread(p, today)]
    if todo:
        lines += ["", f"## Not read back yet ({len(todo)})", "",
                  "Record each with `leads log set URL views=N likes=N` (or result=\"...\").", ""]
        for p in sorted(todo, key=lambda p: p["date"], reverse=True):
            page = insights_url(p["url"])
            lines.append(f"- {p['date']} {p['app'] or '-'} {p['ref']} {p['channel']}: {p['url'] or p['note']}"
                         + (f" (insights: {page})" if page else ""))
    return "\n".join(lines)


def _money(r, f):
    try:
        return float(r.get(f) or 0)
    except ValueError:
        return 0.0


def _post_brief(p):
    return {f: p.get(f, "") for f in ("date", "app", "channel", "ref", "url", "views", "likes", "replies", "result")}


def day_report(sales, posts, day, today=None):
    """One day's sales and posts, for the daily recap: the day by app, the 7 days ending
    that day against the 7 before, how far each store's sales go, the day's posts, and
    the last 7 days' posts with the most views."""
    today = today or date.today().isoformat()
    d = date.fromisoformat(day)
    start = (d - timedelta(days=6)).isoformat()
    prev = ((d - timedelta(days=13)).isoformat(), (d - timedelta(days=7)).isoformat())
    by_day, week = {}, {}
    totals = {"units": 0, "proceeds": 0.0, "sales": 0.0}
    week_total = {"units": 0, "proceeds": 0.0, "units_before": 0, "proceeds_before": 0.0}
    through = {}
    for r in sales:
        units, proceeds = int(r.get("units") or 0), _money(r, "proceeds")
        store = r.get("store") or "?"
        through[store] = max(through.get(store, ""), r["date"])
        if r["date"] == day:
            a = by_day.setdefault(r["app"], {"units": 0, "proceeds": 0.0, "sales": 0.0})
            a["units"] += units; a["proceeds"] += proceeds; a["sales"] += _money(r, "sales")
            totals["units"] += units; totals["proceeds"] += proceeds; totals["sales"] += _money(r, "sales")
        if start <= r["date"] <= day:
            w = week.setdefault(r["app"], {"units": 0, "proceeds": 0.0, "units_before": 0, "proceeds_before": 0.0})
            w["units"] += units; w["proceeds"] += proceeds
            week_total["units"] += units; week_total["proceeds"] += proceeds
        elif prev[0] <= r["date"] <= prev[1]:
            w = week.setdefault(r["app"], {"units": 0, "proceeds": 0.0, "units_before": 0, "proceeds_before": 0.0})
            w["units_before"] += units; w["proceeds_before"] += proceeds
            week_total["units_before"] += units; week_total["proceeds_before"] += proceeds

    def rounded(x):
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in x.items()}
    recent = [p for p in posts if start <= p["date"] <= day and (p.get("views") or "").isdigit()]
    return {
        "date": day,
        "day": {a: rounded(v) for a, v in sorted(by_day.items(), key=lambda kv: -kv[1]["proceeds"])},
        "day_total": rounded(totals),
        "week": {a: rounded(v) for a, v in sorted(week.items(), key=lambda kv: -kv[1]["proceeds"])},
        "week_total": rounded(week_total),
        "sales_through": dict(sorted(through.items())),
        "posts": [_post_brief(p) for p in posts if p["date"] == day],
        "top_posts": [_post_brief(p) for p in sorted(recent, key=lambda p: -int(p["views"]))[:5]],
        "unread": sum(unread(p, today) for p in posts),
    }


def day(when=None, today=None):
    today = today or date.today().isoformat()
    when = when or (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    return day_report(_read(SALES, SALES_FIELDS), _read(POSTS, POST_FIELDS), when, today)


# --- I/O ---

def _read(path, fields):
    if not path.exists():
        return []
    return [dict.fromkeys(fields, "") | r for r in tsv.read(path)[1]]


def tool(name):
    """A command from PATH, else this repo's bin/ or ~/.local/bin: the dashboard's Sync
    button runs from a server that may have been started without them on PATH."""
    if shutil.which(name):
        return shutil.which(name)
    for local in (product.HOME / "bin" / name, Path.home() / ".local/bin" / name):
        if local.exists():
            return str(local)
    return name


def _run(cmd, timeout=600):
    cmd = [tool(cmd[0]), *cmd[1:]]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    return (out.stdout, "") if out.returncode == 0 else (None, (out.stderr or out.stdout).strip()[-300:])


def sync(days=14, today=None, read_days=60):
    today = today or date.today().isoformat()
    start = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    DIR.mkdir(exist_ok=True)
    apps = [p.title for p in product.everything()]
    report = []

    sales, new, pulled = _read(SALES, SALES_FIELDS), [], []
    for store, cmd in (("iOS", "asc-sales"), ("Play", "play-sales")):
        text, err = _run([cmd, "--days", str(days), "--tsv"])
        if text is None:
            report.append(f"{store}: {cmd} failed, kept the old rows ({err})")
            continue
        rows = parse_sales(text, store, apps)
        new += rows
        pulled.append(store)
        report.append(f"{store}: {sum(int(r['units']) for r in rows)} units since {start}")
    tsv.write(SALES, SALES_FIELDS, merge_sales(sales, new, start, pulled))

    posts, new = _read(POSTS, POST_FIELDS), []
    err = refresh_own_reddit()
    if err:
        report.append(err)
    for p in product.everything():
        # First, so an experiment row's note for the same post wins.
        f = p.leads / "reddit-posts.tsv"
        if f.exists():
            new += own_reddit_posts(p.title, tsv.read(f)[1])
    ins = product.DATA / "threads-insights.tsv"
    if ins.exists():
        new += threads_posts(tsv.read(ins)[1], apps)
    for p in product.everything():
        f = p.repo / "docs" / "marketing" / "experiments.tsv"
        if f.exists():
            new += experiment_posts(p.title, tsv.read(f)[1])
    merged = merge_posts(posts, new)
    recent = (date.fromisoformat(today) - timedelta(days=read_days)).isoformat()
    got = read_numbers([r for r in merged if r["date"] >= recent])
    report.append(f"read numbers for {len(got)} YouTube and Reddit posts since {recent}")
    tsv.write(POSTS, POST_FIELDS, merged)
    report.append(f"posts: {len(merged)} logged, {sum(unread(r, today) for r in merged)} not read back")
    return report


def set_post(url, pairs, add=False):
    posts = _read(POSTS, POST_FIELDS)
    row = next((r for r in posts if r["url"] == url), None)
    if row is None:
        if not add:
            raise SystemExit(f"{url} isn't in {POSTS.name}; pass --add with app= and channel=")
        row = _blank(url=url, date=date.today().isoformat(), source="set")
        posts.append(row)
    for pair in pairs:
        k, _, v = pair.partition("=")
        if k not in POST_FIELDS:
            raise SystemExit(f"no field {k!r}; fields: {', '.join(POST_FIELDS)}")
        row[k] = v
    tsv.write(POSTS, POST_FIELDS, merge_posts([], posts))
    return row


def week(since=None, today=None):
    today = today or date.today().isoformat()
    if since:
        start = since
        end = (date.fromisoformat(since) + timedelta(days=6)).isoformat()
    else:  # the last full Monday-to-Sunday week
        t = date.fromisoformat(today)
        end_d = t - timedelta(days=t.weekday() + 1)
        start, end = (end_d - timedelta(days=6)).isoformat(), end_d.isoformat()
    return week_report(_read(SALES, SALES_FIELDS), _read(POSTS, POST_FIELDS), start, end, today)
