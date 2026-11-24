"""Reddit posts and comments through Arctic Shift, a public Reddit archive.

Since 2026-11-10 Reddit answers anonymous search.rss with 403, and its feeds
allow about one request every 30 s. Arctic Shift (arctic-shift.photon-reddit.com,
docs: github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md) archives
posts within minutes and comments within the hour, with no fixed pause. Its
keyword search times out on busy subs, so a run lists each sub's posts back to
the cutoff and `matches` runs the product's search queries locally.

It's a free volunteer service ("no uptime or performance guarantees"), so
reddit.watch falls back to Reddit's own /new feed for a sub it can't list.
Scores and comment counts read 0 or 1 until a post is about 36 hours old.
Mark-posted reads Reddit first, since it needs your replies within minutes,
and comes here when Reddit refuses your feeds (`own_comments`, `own_posts`).
"""
import html, http.client, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "https://arctic-shift.photon-reddit.com/api"
AGENT = "leadkit/0.1"
POST_FIELDS = "id,title,selftext,author,subreddit,created_utc,num_comments"
MAX_PAGES = 20


class Error(Exception):
    pass


def get(path, params, pause=1.0):
    """GET /api/<path> and return its `data`. Raises Error once retries run out."""
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(int(e.headers.get("X-RateLimit-Reset") or 10) + 1, 120)
                print(f"  429 from arctic shift, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            try:  # 400 and 422 carry {"error": "..."}
                body = json.load(e)
            except ValueError:
                raise Error(f"{e.code} for {url}") from None
        except http.client.IncompleteRead:
            # A long page cut off mid-transfer: try again.
            time.sleep(3 * (attempt + 1))
            continue
        except (OSError, ValueError) as e:  # URLError and timeouts are OSErrors
            raise Error(f"{e} for {url}") from None
        time.sleep(pause)
        err = (body or {}).get("error")
        # "Timeout. Maybe slow down a bit": the docs say a second try often works.
        if err and "imeout" in err or err and "timed out" in err:
            time.sleep(3 * (attempt + 1))
            continue
        if err:
            raise Error(f"{err} for {url}")
        return body.get("data")
    raise Error(f"gave up after 3 tries: {url}")


def entry(x):
    """A post in the shape reddit.entries() yields for an RSS entry."""
    stamp = datetime.fromtimestamp(int(x["created_utc"]), timezone.utc).isoformat()
    return {
        "author": x.get("author") or "",
        "title": html.unescape(x.get("title") or "").strip(),
        "url": f"https://www.reddit.com/r/{x['subreddit']}/comments/{x['id']}/",
        "sub": x.get("subreddit") or "",
        "stamp": stamp,
        "posted": stamp[:10],
        "body": html.unescape(x.get("selftext") or ""),
    }


def posts(sub, since, get=get):
    """Every post in r/<sub> since the epoch second `since`, newest first."""
    out, seen, before = [], set(), None
    for _ in range(MAX_PAGES):
        params = {"subreddit": sub, "after": int(since), "limit": "auto", "sort": "desc", "fields": POST_FIELDS}
        if before:
            params["before"] = before
        page = get("posts/search", params) or []
        fresh = [x for x in page if x["id"] not in seen]
        seen.update(x["id"] for x in fresh)
        out += [x for x in fresh if int(x["created_utc"]) >= since]
        if not fresh or len(page) < 100:
            break
        oldest = min(int(x["created_utc"]) for x in page)
        if oldest <= since:
            break
        # +1 keeps posts from the oldest one's second; `seen` drops the repeats.
        before = oldest + 1
    return [entry(x) for x in out]


def own_comments(account, get=get):
    """An account's latest 100 comments, newest first, shaped like RSS entries
    (url is the comment's permalink)."""
    out = []
    for c in get("comments/search", {"author": account, "limit": 100, "sort": "desc"}) or []:
        stamp = datetime.fromtimestamp(int(c["created_utc"]), timezone.utc).isoformat()
        out.append({"author": account, "title": "", "url": "https://www.reddit.com" + c["permalink"],
                    "sub": c.get("subreddit") or "", "stamp": stamp, "posted": stamp[:10],
                    "body": html.unescape(c.get("body") or "")})
    return out


def own_posts(account, get=get):
    """An account's latest 100 posts, newest first, shaped like RSS entries."""
    params = {"author": account, "limit": 100, "sort": "desc", "fields": POST_FIELDS}
    return [entry(x) for x in get("posts/search", params) or []]


def _term(t):
    if t.startswith('"'):
        return re.escape(t.strip('"')).replace(r"\ ", r"\s+")
    return re.escape(t) + "(?:s|es)?"


def matches(query, text):
    """Reddit's query syntax as the configs use it: alternatives joined by OR,
    each a set of words and quoted phrases that all have to appear."""
    for alt in re.split(r"\s+OR\s+", query.strip()):
        terms = re.findall(r'"[^"]+"|\S+', alt)
        if terms and all(re.search(rf"(?<!\w){_term(t)}(?!\w)", text, re.I) for t in terms):
            return True
    return False


def post_id(url):
    m = re.search(r"/comments/(\w+)", url or "")
    return m.group(1).lower() if m else url.strip().lower().removeprefix("t3_")


def thread(url, get=get):
    """A post and its comments as (depth, comment) in reading order."""
    pid = post_id(url)
    (p,) = get("posts/ids", {"ids": pid, "fields": POST_FIELDS}) or [None]
    if not p:
        raise Error(f"arctic shift has no post {pid}")
    tree = get("comments/tree", {"link_id": f"t3_{pid}", "limit": 9999}) or []
    comments = []

    def walk(items, depth):
        for x in items:
            if x.get("kind") == "more":
                continue
            d = x.get("data", x)
            comments.append((depth, d))
            r = d.get("replies")
            walk(r.get("data", {}).get("children", []) if isinstance(r, dict) else [], depth + 1)
    walk(tree, 0)
    return {"post": entry(p) | {"comments": p.get("num_comments")}, "comments": comments}


def show_thread(url, get=get):
    """Print a thread for reading during triage (`leads thread URL`)."""
    t = thread(url, get=get)
    p, now = t["post"], datetime.now(timezone.utc)

    def age(stamp):
        h = (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
        return f"{h:.0f}h" if h < 48 else f"{h / 24:.0f}d"
    print(f"r/{p['sub']} · u/{p['author']} · {age(p['stamp'])} ago · {len(t['comments'])} comments archived")
    print(p["title"])
    print(p["url"])
    if p["body"].strip():
        print("\n" + p["body"].strip())
    for depth, c in t["comments"]:
        stamp = datetime.fromtimestamp(int(c.get("created_utc") or 0), timezone.utc).isoformat()
        pad = "    " * depth
        body = html.unescape(c.get("body") or "").strip().replace("\n", "\n" + pad + "  ")
        print(f"\n{pad}- u/{c.get('author')} ({age(stamp)} ago): {body}")
