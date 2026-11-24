"""Reddit's two kinds of sub, and the posting side of them.

A product's subs are split in its config:

- SUBREDDITS (and GROUPS): answer subs. People ask questions there, the
  watcher finds them, and a reply answers first (r/Sourdough for a baking app).
- POST_SUBS: ad subs. You post an ad of your own there, under the sub's
  rules (a "Showcase" flair, say). A sub can be in both: a device's sub can
  take showcase posts and have owners asking for apps.

They're split because one showcase post of your own can do more in a sub than
dozens of replies there, and the funnel in `leads stats` only covers replies.

POST_SUBS = {"sub": {key: value}} with these keys, all optional:
  flair        the flair an ad needs there
  every_days   how often the rules allow an ad (unset: no limit recorded)
  per_account  True when that limit counts every app's posts (r/iosapps:
               once per developer per 30 days)
  not_before   no ad before this date (r/iosapps: the app 30+ days on the store)
  thread       the ad goes in this recurring thread as a comment, not a post
               (a sub's monthly self-promo megathread); not tracked yet
  rules        what the post has to do there, in a line

`leads posts` reads the account's posts from Arctic Shift (scores settle about
36 hours after posting), keeps the ones naming the app in leads/reddit-posts.tsv,
and says when each ad sub takes the next one. The shared app threads ("what are
you building this week", leadkit/kinds.py) are ads too, so it lists the open ones.
"""
import re
from datetime import date, datetime, timedelta, timezone

from . import arctic, kinds, product, tsv

KEYS = {"flair", "every_days", "per_account", "not_before", "thread", "rules"}
FIELDS = ["posted", "sub", "flair", "title", "url", "score", "comments", "checked"]
OWN_FIELDS = "id,title,selftext,subreddit,created_utc,num_comments,score,link_flair_text,author"


def path(p):
    return p.leads / "reddit-posts.tsv"


def read(p):
    return tsv.read(path(p))[1]


def fetch_own(get=arctic.get):
    """Every post the reply account has made, newest first (Arctic Shift)."""
    return get("posts/search", {"author": product.settings.REDDIT_REPLY_ACCOUNT, "limit": 100, "sort": "desc",
                                "fields": OWN_FIELDS}) or []


def mine(p, found):
    """The posts that are this product's: its store ID in the body, or its name."""
    sid = str(p.get("APP_STORE_ID") or "")
    name = re.compile(rf"\b{re.escape(p.title)}\b", re.I)
    return [x for x in found
            if (sid and f"id{sid}" in (x.get("selftext") or ""))
            or name.search(f"{x.get('title') or ''}\n{x.get('selftext') or ''}")]


def _day(x):
    return datetime.fromtimestamp(int(x["created_utc"]), timezone.utc).date().isoformat()


def _sub_day(x):
    """(sub, day) of an Arctic Shift post or a logged row."""
    if "subreddit" in x:
        return x["subreddit"].lower(), _day(x)
    return x["sub"].lower(), x["posted"]


def log(p, found, today=None):
    """Add or refresh a row per post of this product's. Returns the rows."""
    today = today or date.today().isoformat()
    rows = {r["url"]: r for r in read(p)}
    for x in found:
        url = f"https://www.reddit.com/r/{x['subreddit']}/comments/{x['id']}/"
        r = rows.setdefault(url, dict.fromkeys(FIELDS, "") | {"url": url})
        r.update(posted=_day(x), sub=x["subreddit"], title=(x.get("title") or "").strip(),
                 score=str(x.get("score", "")), comments=str(x.get("num_comments", "")), checked=today)
        r["flair"] = x.get("link_flair_text") or r.get("flair") or ""
    out = sorted(rows.values(), key=lambda r: r["posted"], reverse=True)
    if out:
        p.leads.mkdir(parents=True, exist_ok=True)
        tsv.write(path(p), FIELDS, out)
    return out


def due(p, logged, everyone, today=None):
    """For each ad sub: the product's last post there and when the next is allowed.
    `everyone` is the account's posts for every app (Arctic Shift posts or
    logged rows), for per_account limits."""
    today = today or date.today()
    out = []
    for sub, rule in p.get("POST_SUBS", {}).items():
        here = sorted((r for r in logged if r["sub"].lower() == sub.lower()), key=lambda r: r["posted"])
        last = here[-1] if here else None
        if rule.get("thread"):
            out.append({"sub": sub, "rule": rule, "last": last, "next": f"comment in the {rule['thread']}"})
            continue
        dates = [r["posted"] for r in here]
        if rule.get("per_account"):
            dates += [_sub_day(x)[1] for x in everyone if _sub_day(x)[0] == sub.lower()]
        start = None
        if dates and rule.get("every_days"):
            start = date.fromisoformat(max(dates)) + timedelta(days=rule["every_days"])
        if rule.get("not_before"):
            nb = date.fromisoformat(rule["not_before"])
            start = max(start, nb) if start else nb
        if start and start > today:
            nxt = start.isoformat()
        elif dates and not rule.get("every_days") and not start:
            nxt = "no limit recorded"
        else:
            nxt = "now"
        out.append({"sub": sub, "rule": rule, "last": last, "next": nxt})
    return out


def open_app_threads(p, today):
    """Open app-kind rows found in the last few days; older weekly threads have moved on."""
    days = -(-kinds.APP["showcase_max_hours"] // 24)
    since = (today - timedelta(days=days)).isoformat()
    _, rows = tsv.read(p.reddit_tsv)
    return [r for r in rows if kinds.of(r) == kinds.APP_KIND and tsv.status(r) in tsv.OPEN
            and (r.get("found") or "") >= since]


def describe(r):
    return f"{r['posted']}  {r.get('score') or '?'} pts  {r.get('comments') or '?'} comments  {r['title'][:60]}"


def report(p, fetch=fetch_own, today=None):
    """fetch=None reads only the log (no network)."""
    today = today or date.today()
    everyone = []
    if fetch:
        everyone = fetch()
        logged = log(p, mine(p, everyone), today=today.isoformat())
    else:
        logged = read(p)
        everyone = [r for name in product.names() for r in tsv.read(product.Product(name).leads / path(p).name)[1]]
    lines = [f"{p.title}: ad subs"]
    rows = due(p, logged, everyone, today)
    if not rows:
        lines.append("  none in POST_SUBS")
    for d in rows:
        rule = d["rule"]
        last = describe(d["last"]) if d["last"] else "no post yet"
        extra = ", ".join(f"{k} {rule[k]}" for k in ("flair",) if rule.get(k))
        lines.append(f"  r/{d['sub']:<16} next: {d['next']:<22} last: {last}" + (f"  ({extra})" if extra else ""))
        if rule.get("rules"):
            lines.append(f"  {'':18} {rule['rules']}")
    elsewhere = [r for r in logged if r["sub"].lower() not in {s.lower() for s in p.get("POST_SUBS", {})}]
    if elsewhere:
        lines += ["", "Own posts in subs not in POST_SUBS"] + [f"  r/{r['sub']:<16} {describe(r)}" for r in elsewhere]
    threads = open_app_threads(p, today)
    lines += ["", "Open app threads from the last few days (an ad as a comment)"]
    lines += [f"  {r.get('found')}  r/{r.get('subreddit')}  {r.get('title')}  {r['url']}" for r in threads] or ["  none"]
    return "\n".join(lines)
