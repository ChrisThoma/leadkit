"""leads stats: is the leads pass working? Read from the leads TSVs alone.

Every row ends in one outcome (posted, open, a skip of some sort), and every row
was either drafted (a reply was written) or not. Counting those by platform and
kind, by subreddit, by the watcher's score and by week says where the time goes:
which subs only ever bring skips, whether a high score predicts a post, and how
many drafts expire or get turned down on the drafts page.

What a posted reply did afterwards (votes, replies, clicks) isn't in the TSVs
yet, so this stops at posted. Ads of your own in the ad subs (POST_SUBS) are
listed with their score from leads/reddit-posts.tsv, as of the last `leads posts`.
"""
import re
from collections import Counter
from datetime import date, timedelta

from . import drafts, kinds, posts, tsv

OUTCOMES = ("posted", "open", "you skipped", "expired", "draft dropped", "triage skip", "untriaged")
BANDS = ("10+", "8-9", "6-7", "5", "no score")
SCORE = re.compile(r"Watcher \[(-?\d+)\]")
REASON = re.compile(re.escape(drafts.SKIP_NOTE) + r"(?: Reason: (.*?)\.?)?(?:$|\")")


def drafted(r):
    return bool((r.get("reply") or "").strip()) or tsv.status(r) in ("posted", "replied")


def outcome(r):
    s, notes = tsv.status(r), r.get("notes") or ""
    if s in ("posted", "replied"):
        return "posted"
    if s in tsv.OPEN:
        return "open"
    if drafts.SKIP_NOTE in notes:
        return "you skipped"
    if notes.startswith("Cleared "):
        return "expired"
    if notes.startswith("Never triaged"):
        return "untriaged"
    return "draft dropped" if drafted(r) else "triage skip"


def band(r):
    m = SCORE.search(r.get("notes") or "")
    if not m:
        return "no score"
    s = int(m.group(1))
    return "10+" if s >= 10 else "8-9" if s >= 8 else "6-7" if s >= 6 else "5"


def week(r):
    try:
        d = date.fromisoformat((r.get("found") or "").strip()[:10])
    except ValueError:
        return "no date"
    return (d - timedelta(days=d.weekday())).isoformat()


def reasons(rows):
    out = Counter()
    for r in rows:
        notes = r.get("notes") or ""
        if drafts.SKIP_NOTE in notes:
            m = REASON.search(notes)
            out[(m.group(1) if m and m.group(1) else "(none given)").strip()] += 1
    return dict(out)


def _load(p, since):
    out = []
    for platform, path in (("Reddit", p.reddit_tsv), ("Threads", p.threads_tsv), ("X", p.x_tsv)):
        _, rows = tsv.read(path)
        out += [r | {"_platform": platform} for r in rows if not since or (r.get("found") or "") >= since]
    return out


def _counts(rows):
    return len(rows), sum(drafted(r) for r in rows), sum(outcome(r) == "posted" for r in rows)


def _pct(a, b):
    return f"{100 * a // b}%" if b else "-"


def _table(title, label, groups, width=18):
    lines = [title, f"  {label:<{width}} {'found':>6} {'drafted':>8} {'posted':>7} {'draft>post':>11}"]
    for name, rows in groups:
        n, d, posted = _counts(rows)
        lines.append(f"  {name:<{width}} {n:>6} {d:>8} {posted:>7} {_pct(posted, d):>11}")
    return lines


def _group(rows, key):
    out = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return out


def product_report(p, since=None, min_found=10, weeks=8):
    rows = _load(p, since)
    lines = [f"{p.title}" + (f" (found since {since})" if since else ""), ""]
    own = [r for r in posts.read(p) if not since or r["posted"] >= since]
    mine = ["", "Own posts (as of the last `leads posts`)"]
    mine += [f"  r/{r['sub']:<16} {posts.describe(r)}" for r in own] or ["  none logged"]
    if not rows:
        return "\n".join(lines + ["  no leads"] + mine)

    by_kind = _group(rows, lambda r: f"{r['_platform']} {kinds.of(r)}")
    lines += _table("Funnel", "", sorted(by_kind.items()))

    lines += ["", "Where rows ended"]
    for name, group in sorted(_group(rows, lambda r: r["_platform"]).items()):
        c = Counter(outcome(r) for r in group)
        lines.append(f"  {name}: " + ", ".join(f"{o} {c[o]}" for o in OUTCOMES if c[o]))

    reddit = [r for r in rows if r["_platform"] == "Reddit"]
    subs = _group(reddit, lambda r: ("r/" + r["subreddit"].strip()) if (r.get("subreddit") or "").strip() else "(no sub)")
    busy = sorted(((s, g) for s, g in subs.items() if len(g) >= min_found), key=lambda x: -len(x[1]))
    if busy:
        lines += [""] + _table(f"Reddit subs with {min_found}+ leads, most first", "sub", busy, 22)
        dead = [f"{s} ({len(g)})" for s, g in busy if not any(drafted(r) for r in g)]
        if dead:
            lines.append("  Never drafted: " + ", ".join(dead))

    scored = _group(reddit, band)
    if scored:
        lines += [""] + _table("Reddit by watcher score", "score", [(b, scored[b]) for b in BANDS if b in scored])

    recent = sorted(_group(rows, week).items(), reverse=True)[:weeks]
    lines += [""] + _table("By week found (Monday)", "week", recent)

    lines += mine

    why = reasons(rows)
    lines += ["", "Skip reasons on the drafts page"]
    lines += [f"  {n:>4}  {k}" for k, n in sorted(why.items(), key=lambda x: -x[1])] or ["  none"]
    return "\n".join(lines)


def report(products, since=None, min_found=10):
    parts = []
    if len(products) > 1:
        lines = _table("All products" + (f" (found since {since})" if since else ""), "",
                       [(p.title, _load(p, since)) for p in products])
        parts.append("\n".join(lines))
    parts += [product_report(p, since, min_found) for p in products]
    return ("\n\n" + "-" * 60 + "\n\n").join(parts)
