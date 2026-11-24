"""Find Reddit threads where someone is asking for what a product does.

Reads Reddit's public Atom feeds (the JSON endpoints return 403 without OAuth,
the .rss ones don't) and appends unseen matches to the product's
reddit-leads.tsv, where you mark each one replied or skipped. Nothing here
posts to Reddit: the reply is written by a person, as a member of the
community, and mentions the app only when it actually answers the question.

Reddit rate-limits anonymous feed reads hard, about one request per 30 to 40
seconds, so every fetch is spaced out and a 429 backs off rather than failing
the run.
"""
import html, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from . import arctic, kinds, tsv
from .product import settings

FIELDS = ["found", "posted", "priority", "subreddit", "author", "title", "url", "engagement", "pitch", "reply", "notes", "status", "kind"]
NS = {"a": "http://www.w3.org/2005/Atom"}
USER_AGENT = f"leadkit/0.1 (by {getattr(settings, 'CONTACT', 'leadkit')})"


class _Forbidden(bytes):
    """A 403: falsy like no data, but watch() can tell it from a network blip."""


FORBIDDEN = _Forbidden()


def fetch(url, pause, agent=USER_AGENT):
    req = urllib.request.Request(url, headers={"User-Agent": agent})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            time.sleep(pause)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * (attempt + 1)  # observed: a minute is usually enough
                print(f"  429 from reddit, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  {e.code} for {url}", file=sys.stderr)
            return FORBIDDEN if e.code == 403 else None
        except Exception as e:  # network blip: skip this feed, keep the run
            print(f"  {e} for {url}", file=sys.stderr)
            return None
    return None


def post_id(url):
    # Leads are keyed by post ID: hand-found rows may hold short /comments/<id>/
    # URLs and Reddit varies the subreddit's case (GameDev vs gamedev).
    m = re.search(r"/comments/(\w+)", url or "")
    return m.group(1).lower() if m else None


def allowed(p, sub):
    return (sub or "").lower() not in p.get("EXCLUDED", set())


def entries(data):
    root = ET.fromstring(data)
    for e in root.findall("a:entry", NS):
        link = e.find("a:link", NS)
        content = e.find("a:content", NS)
        category = e.find("a:category", NS)
        body = html.unescape(re.sub(r"<[^>]+>", " ", content.text or "")) if content is not None else ""
        author = (e.findtext("a:author/a:name", "", NS) or "").strip().removeprefix("/u/")
        stamp = (e.findtext("a:published", "", NS) or e.findtext("a:updated", "", NS) or "").strip()
        yield {
            "author": author,
            "title": (e.findtext("a:title", "", NS) or "").strip(),
            "url": link.get("href") if link is not None else "",
            "sub": category.get("term", "") if category is not None else "",
            "stamp": stamp,
            "posted": stamp[:10],
            "body": body,
        }


def age_hours(stamp, now):
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
    except ValueError:
        return 0.0


def score(p, text, tables=None):
    """Sum the weighted phrases (the product's, unless `tables` names a kind's).
    A gated table counts only when its gate matches."""
    t = text.lower()
    total, hits = 0, []
    for gate, table in tables or p.need("SCORE_TABLES"):
        if gate and not re.search(gate, t):
            continue
        for pat, w in table.items():
            if re.search(pat, t):
                total += w
                hits.append(pat)
    return total, hits


def load_seen(p):
    _, rows = tsv.read(p.reddit_tsv)
    seen = {post_id(r.get("url")) for r in rows}
    seen.discard(None)
    return seen


def submit_sub(url):
    """The subreddit of a queued post of our own (a row whose URL is r/<sub>/submit)."""
    m = re.search(r"/r/(\w+)/submit/?$", url or "")
    return m.group(1).lower() if m else None


def for_another_app(p, text):
    """True when a comment names another of your apps and not this one. You answer
    from one account, so a thread can hold replies for two apps, and a reply for
    one app mustn't mark the other app's draft there as posted. A comment that
    names no app (a plain answer) still counts."""
    def names(title):
        return re.search(rf"\b{re.escape(title)}\b", text or "", re.I)
    if names(p.title):
        return False
    from .product import everything
    return any(names(o.title) for o in everything() if o.name != p.name)


def own_feed(kind, account, pause, agent, fetch, arctic_get):
    """The account's comments or submissions, newest first: Reddit's feed, or
    Arctic Shift when Reddit refuses it. The comment feed can answer 404, and
    posted replies would stay open on the drafts page."""
    data = fetch(f"https://www.reddit.com/user/{account}/{kind}/.rss?limit=100", pause, agent)
    if data and data is not FORBIDDEN:
        return list(entries(data))
    print(f"  reading u/{account}'s {kind} from arctic shift instead", file=sys.stderr)
    try:
        if kind == "comments":
            return arctic.own_comments(account, get=arctic_get)
        return arctic.own_posts(account, get=arctic_get)
    except arctic.Error as err:
        print(f"  arctic shift failed too ({err})", file=sys.stderr)
        return []


def mark_posted(p, pause=None, fetch=fetch, arctic_get=arctic.get):
    """Mark every queued row you've since commented on, or posted to its sub, as posted."""
    pause = p.get("PAUSE", 35.0) if pause is None else pause
    agent = p.get("USER_AGENT", USER_AGENT)
    account = settings.REDDIT_REPLY_ACCOUNT
    if not tsv.read(p.reddit_tsv)[1]:
        return 0
    mine = own_feed("comments", account, pause, agent, fetch, arctic_get)
    mine_posts = own_feed("submitted", account, pause, agent, fetch, arctic_get)
    # Read the rows only now. The feeds can take minutes of 429 waits, and
    # rows read before them would be written back over a draft that
    # `leads set` added meanwhile.
    fields, rows = tsv.read(p.reddit_tsv)
    # A follow-up draft shares its post ID with the row you already answered,
    # so a comment another row records doesn't count, or the follow-up would be
    # marked posted by the earlier reply before you wrote it.
    claimed = "\n".join(r.get("notes") or "" for r in rows)
    comments = {}
    for e in mine:
        pid = post_id(e["url"])
        if pid and e["url"] not in claimed and not for_another_app(p, e["body"]):
            comments.setdefault(pid, []).append(e["url"])
    # Posts of your own: the newest submission in each sub, with its date.
    submitted = {}
    for e in mine_posts:
        if e["url"] not in claimed:
            submitted.setdefault(e["sub"].lower(), (e["posted"], e["url"]))
    marked = 0
    for r in rows:
        if tsv.status(r) not in ("new", "draft", "skip"):
            continue
        unclaimed = comments.get(post_id(r["url"]))
        url = unclaimed.pop() if unclaimed else None
        post = submitted.get(submit_sub(r["url"]))
        if not url and post and post[0] >= (r.get("found") or ""):
            url = post[1]
            submitted.pop(submit_sub(r["url"]))
        if url:
            r["status"] = "posted"
            r["notes"] = f"{'Post' if submit_sub(r['url']) else 'Comment'}: {url} {r.get('notes') or ''}".strip()
            print(f"posted: {p.title}: {r.get('title') or r['url']}", file=sys.stderr)
            marked += 1
    if marked:
        tsv.write(p.reddit_tsv, fields, rows)
    return marked


def feeds(p, subreddits=None):
    """Every Reddit feed URL a run reads, in order."""
    return [url for url, _ in feed_kinds(p, subreddits)]


def search_url(q, multi=None):
    if multi:
        qs = urllib.parse.urlencode({"q": q, "sort": "new", "restrict_sr": 1, "t": "week", "limit": 100})
        return f"https://www.reddit.com/r/{multi}/search.rss?{qs}"
    qs = urllib.parse.urlencode({"q": q, "sort": "new", "t": "week", "limit": 100})
    return f"https://www.reddit.com/search.rss?{qs}"


def specs(p, subreddits=None):
    """What a run reads, whatever the source: dicts of `subs` (None for a
    site-wide search), `query` (None for every post), `kind` and `showcase`.
    The product's domain feeds come first, then the shared app-kind searches
    (kinds.APP) unless the product opts out."""
    subs = [s for s in (subreddits or p.need("SUBREDDITS")) if allowed(p, s)]
    out = [dict(subs=[sub], query=None) for sub in p.get("NEW_FEEDS", []) if sub in subs]
    # Each query runs once against all the subs joined as a multireddit
    # (r/a+b+c), not once per sub, to keep a Reddit run near fifteen requests.
    groups = [{"subreddits": subs, "searches": p.get("SEARCHES", [])}] + p.get("GROUPS", [])
    for g in groups:
        out += [dict(subs=list(g["subreddits"]) or None, query=q) for q in g.get("searches", [])]
    # Site-wide searches reach every sub in one request.
    site = list(p.get("SITE_SEARCHES", []))
    for g in p.get("GROUPS", []):
        site += g.get("site_searches", [])
    out = [s | dict(kind=kinds.DOMAIN, showcase=False) for s in out + [dict(subs=None, query=q) for q in site]]
    if kinds.enabled(p) and not subreddits:
        out += [dict(subs=None, query=q, kind=kinds.APP_KIND, showcase=False) for q in kinds.APP["site_searches"]]
        app_subs = list(kinds.APP.get("subreddits", []))
        if app_subs:
            out += [dict(subs=app_subs, query=q, kind=kinds.APP_KIND, showcase=True)
                    for q in kinds.APP.get("searches", [])]
    return out


def spec_url(s):
    """The Reddit feed for a spec."""
    if s["query"] is None:
        return f"https://www.reddit.com/r/{s['subs'][0]}/new.rss?limit=100"
    return search_url(s["query"], "+".join(s["subs"]) if s["subs"] else None)


def feed_kinds(p, subreddits=None):
    """(url, kind) for every Reddit feed a run reads."""
    return [(spec_url(s), s["kind"]) for s in specs(p, subreddits)]


def showcase_feeds():
    """The shared show-your-work subs' Reddit searches (kinds.APP["subreddits"])."""
    multi = "+".join(kinds.APP.get("subreddits", []))
    return [search_url(q, multi) for q in kinds.APP.get("searches", [])] if multi else []


def watch(p, days=7, pause=None, dry_run=False, subreddits=None, min_score=None, posted_only=False, fetch=fetch,
          source="arctic", arctic_get=arctic.get, near_misses=False):
    """Find new leads. source="arctic" lists each sub through Arctic Shift and
    runs the searches locally (Reddit's own search has refused since
    2026-11-10); source="reddit" reads Reddit's feeds, one every `pause` s.
    near_misses=True appends the near misses as leads too, for the hourly job:
    good leads often score just under the bar, and its triage reads each one
    the way a pass does."""
    pause = p.get("PAUSE", 35.0) if pause is None else pause
    min_score = p.need("MIN_SCORE") if min_score is None else min_score
    agent = p.get("USER_AGENT", USER_AGENT)
    if not dry_run:
        mark_posted(p, pause, fetch)
    if posted_only:
        return []

    seen = load_seen(p)
    now = datetime.now(timezone.utc)
    today = now.date()
    found, maybe = {}, {}
    own_accounts = settings.REDDIT_OWN_ACCOUNTS
    search_refused, site_skipped, listings = False, 0, {}
    since = now.timestamp() - days * 86400

    def listed(sub):
        """r/<sub>'s posts since the cutoff, from Arctic Shift or else Reddit's /new feed."""
        if sub not in listings:
            print(f"listing r/{sub}", file=sys.stderr)
            try:
                listings[sub] = arctic.posts(sub, since, get=arctic_get)
            except arctic.Error as err:
                print(f"  arctic shift failed ({err}); reading r/{sub}/new from Reddit", file=sys.stderr)
                data = fetch(f"https://www.reddit.com/r/{sub}/new.rss?limit=100", pause, agent)
                listings[sub] = list(entries(data)) if data else []
        return listings[sub]

    for s in specs(p, subreddits):
        kind = s["kind"]
        app = kind == kinds.APP_KIND
        tables = kinds.APP["score_tables"] if app else None
        floor = kinds.APP["min_score"] if app else min_score
        app_hours = kinds.APP["showcase_max_hours"] if s["showcase"] else kinds.APP["max_hours"]
        max_hours = min(days * 24, app_hours) if app else days * 24
        if source == "arctic":
            if s["subs"] is None:  # a site-wide search: nothing to list
                site_skipped += 1
                continue
            posts = [e for sub in s["subs"] for e in listed(sub)]
            if s["query"]:
                posts = [e for e in posts if arctic.matches(s["query"], e["title"] + "\n" + e["body"])]
        else:
            url = spec_url(s)
            # Since 2026-11-10 anonymous search.rss answers 403, usually after a
            # 429 that costs a minute. One refusal means the rest will refuse too.
            if search_refused and "/search.rss" in url:
                continue
            print(f"fetching {url}", file=sys.stderr)
            data = fetch(url, pause, agent)
            if data is FORBIDDEN and "/search.rss" in url:
                search_refused = True
                print("  reddit refused search; skipping this run's other searches", file=sys.stderr)
            if not data:
                continue
            posts = entries(data)
        for e in posts:
            pid = post_id(e["url"])
            if not pid or pid in seen or pid in found or pid in maybe:
                continue
            if e["author"].lower() in own_accounts or not allowed(p, e["sub"]):
                continue
            hours = age_hours(e["stamp"], now)
            if hours > max_hours:
                continue
            s, hits = score(p, e["title"] + "\n" + e["body"], tables)
            row = {"score": s, "subreddit": e["sub"], "posted": e["posted"], "hours": hours,
                   "title": e["title"], "url": e["url"], "kind": kind}
            snippet = " ".join(e["body"].split())[:280]
            if s < floor:
                if s >= 1:
                    maybe[pid] = row | {"found": today.isoformat(), "author": e["author"], "status": "new",
                                        "notes": f"Near miss [{s}]. {snippet}"}
                continue
            # A sub added before anyone read its sidebar: the first reply
            # there waits for a rules check, so the lead carries the reminder.
            unchecked = e["sub"].lower() in {s.lower() for s in p.get("RULES_UNCHECKED", ())}
            rules = f"Rules unchecked for r/{e['sub']}: read the sidebar before replying. " if unchecked else ""
            if app:
                rules = (f"App thread. Check r/{e['sub']}'s self-promotion rules before the first reply there; "
                         "the reply is the pitch, with a link. ")
            found[pid] = row | {
                "found": today.isoformat(),
                "author": e["author"],
                "status": "new",
                "notes": f"{rules}Watcher [{s}]. {snippet}",
            }

    # Age is printed because it decides most skips: a good question that is
    # two days old has usually been answered well already.
    def show(r):
        tag = " app" if r.get("kind") == kinds.APP_KIND else ""
        print(f"[{int(r['score']):>2}{tag}] r/{r['subreddit']} {r['hours']:.0f}h ago  {r['title']}\n      {r['url']}")

    if site_skipped:
        print(f"skipped {site_skipped} site-wide search(es): they need Reddit's own search", file=sys.stderr)
    stamps = [e["stamp"] for es in listings.values() for e in es]
    if stamps:
        lag = age_hours(max(stamps), now)
        if lag > 6:
            print(f"warning: the newest listed post is {lag:.0f}h old, so Arctic Shift may be behind; "
                  "`leads reddit --source reddit` reads Reddit directly", file=sys.stderr)

    rows = sorted(found.values(), key=lambda r: (-r["score"], r["hours"]))
    for r in rows:
        show(r)
    print(f"{len(rows)} new lead(s)", file=sys.stderr)

    # Near misses are printed, never appended: the phrase table can't name
    # every way someone asks, and a skim of what almost scored is where the
    # table gets tuned from and where the manual finds come from.
    if maybe:
        print("\nnear misses (added for triage):" if near_misses and not dry_run else "\nnear misses (not added):")
        for r in sorted(maybe.values(), key=lambda r: (-r["score"], r["hours"])):
            show(r)

    if near_misses:
        rows += sorted(maybe.values(), key=lambda r: (-r["score"], r["hours"]))
    if dry_run or not rows:
        return rows
    # The listing takes minutes, and a session may log one of these threads
    # by hand meanwhile; don't add a second row for it.
    seen = load_seen(p)
    rows = [r for r in rows if post_id(r.get("url")) not in seen]
    if not rows:
        return rows
    tsv.ensure(p.reddit_tsv, ["kind"])
    tsv.append(p.reddit_tsv, rows, FIELDS)
    print(f"appended to {p.reddit_tsv}", file=sys.stderr)
    return rows


def labels(p):
    """Posts you've judged: a priority or posted is worth answering, a skip is not."""
    out = {}
    for r in tsv.read(p.reddit_tsv)[1]:
        pid = post_id(r.get("url"))
        if not pid:
            continue
        if (r.get("priority") or "").strip() or tsv.status(r) == "posted":
            out[pid] = "good"
        # A stale watcher row nobody looked at is not a judgement either way.
        elif tsv.status(r) == "skip" and not (r.get("notes") or "").startswith(("Never triaged", "Cleared ")):
            out[pid] = "bad"
    return out


def evaluate(p, verbose=False, fetch=fetch):
    """Score every post you've already judged with the product's current table.

    The posts are fetched 25 at a time from Reddit's /by_id/ feed, so a check
    is a handful of requests rather than one per post.
    """
    lab = labels(p)
    ids = sorted(lab)
    rows = []
    for k in range(0, len(ids), 25):
        names = ",".join("t3_" + i for i in ids[k:k + 25])
        data = fetch(f"https://www.reddit.com/by_id/{urllib.parse.quote(names, safe=',_')}.rss", 20,
                     p.get("USER_AGENT", USER_AGENT))
        if not data:
            print("  batch failed; counts below are partial", file=sys.stderr)
            continue
        for e in entries(data):
            pid = post_id(e["url"])
            s, _ = score(p, e["title"] + "\n" + e["body"])
            rows.append((lab.get(pid, "?"), s, e["sub"], e["title"][:80]))
    min_score = p.need("MIN_SCORE")
    for label in ("good", "bad"):
        group = [r for r in rows if r[0] == label]
        lead = sum(r[1] >= min_score for r in group)
        near = sum(1 <= r[1] < min_score for r in group)
        print(f"{label}: {len(group)} posts, {lead} scored as leads, {near} near misses, {len(group) - lead - near} unscored")
    if verbose:
        for r in sorted(rows, key=lambda r: (r[0], -r[1])):
            print(f"{r[0]:4} {r[1]:3} r/{r[2]:15} {r[3]}")
