"""leads threads-yield: which Threads searches find threads worth replying to.

Each Threads lead records the search that found it (the `query` column, or the
older notes), and `threads-replies.tsv` records how many views each reply of
ours got. Joining the two, per query and per kind, says which searches are worth
running and which only bring leads nobody answers. No API calls: both sides are
files, so run `leads threads-insights` first for fresh views.

A reply's API record names neither its parent nor its root post when the parent
is someone else's, so the join runs through the lead row: the shortcode in its
`Reply: <url>` note, else its `reply_id` column.
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher
from statistics import median

from . import kinds, threads, tsv

POSTED = ("posted", "replied")
NEVER_MIN = 8  # leads found from one query, with none posted, before it's called out
NO_QUERY = "(not recorded)"
REPLY_NOTE = re.compile(r"Reply:\s*(\S+)")
CODE = re.compile(r"/post/([^/?#\s]+)")


def code_of(url):
    """A Threads post's shortcode, whatever the host, query string or trailing slash."""
    m = CODE.search(url or "")
    return m.group(1) if m else ""


def index(replies):
    """({shortcode: reply}, {id: reply}) for the replies file's rows."""
    return ({code_of(r["url"]): r for r in replies if code_of(r.get("url"))},
            {r["id"]: r for r in replies if r.get("id")})


def reply_code(row):
    m = REPLY_NOTE.search(row.get("notes") or "")
    return code_of(m.group(1)) if m else ""


def squash(text, n=60):
    """A reply's first words, for comparing a drafted text to the posted one:
    lowercase, whitespace collapsed, anything but letters, digits and spaces dropped."""
    text = re.sub(r"[^\w ]|_", "", re.sub(r"\s+", " ", (text or "").lower()))
    return re.sub(r" +", " ", text).strip()[:n]


class Join:
    """Which reply answered which lead, built once over every product so a reply
    is used by one row only. Pass 1 takes the explicit links (the `Reply:` note's
    shortcode, else `reply_id`). Pass 2 pairs posted rows still unlinked with an
    unused reply whose first 60 characters match the row's drafted text: the
    rows marked replied on the drafts page never got a
    note. With several candidates (one pitch posted in several threads) the date
    decides."""
    SIMILAR = 0.8

    def __init__(self, products, replies):
        self.rows = {p.name: tsv.read(p.threads_tsv)[1] for p in products}
        self.reply, self.by_text, self.used = {}, set(), set()
        by_code, by_id = index(replies)
        everyone = [r for rows in self.rows.values() for r in rows]
        for r in everyone:
            hit = by_code.get(reply_code(r)) or by_id.get((r.get("reply_id") or "").strip())
            if hit and hit["url"] not in self.used:
                self.reply[id(r)] = hit
                self.used.add(hit["url"])
        todo = sorted((r for r in everyone if id(r) not in self.reply and tsv.status(r) in POSTED
                       and threads._reply_text(r)), key=lambda r: r.get("found") or "")
        for r in todo:
            hit = self._by_text(r, replies)
            if hit:
                self.reply[id(r)] = hit
                self.by_text.add(id(r))
                self.used.add(hit["url"])

    def _by_text(self, row, replies):
        want = squash(threads._reply_text(row))
        found = (row.get("found") or "")[:10]
        near = [r for r in replies if r["url"] not in self.used and want and
                SequenceMatcher(None, want, squash(r.get("text"))).ratio() >= self.SIMILAR]
        after = sorted((r for r in near if r["posted"][:10] >= found), key=lambda r: r["posted"])
        before = sorted((r for r in near if r["posted"][:10] < found), key=lambda r: r["posted"])
        return (after or before[::-1] or [None])[0]

    def of(self, row):
        return self.reply.get(id(row))


def _views(reply):
    try:
        return int(reply["views"])
    except (KeyError, TypeError, ValueError):
        return None


def _load(p, join, since):
    return [r for r in join.rows[p.name] if not since or (r.get("found") or "") >= since]


def _stats(rows, join, min_views):
    """found, posted, seen (posted with known views), median, best, reached min_views."""
    posted = [r for r in rows if tsv.status(r) in POSTED]
    views = [v for v in (_views(join.of(r) or {}) for r in posted) if v is not None]
    return {"found": len(rows), "posted": len(posted), "seen": len(views),
            "median": median(views) if views else None, "best": max(views, default=None),
            "reached": sum(v >= min_views for v in views)}


def _table(title, label, groups, join, min_views):
    stats = [(name, _stats(rows, join, min_views)) for name, rows in groups.items()]
    stats.sort(key=lambda x: (-x[1]["posted"], -x[1]["found"], x[0]))
    head = f"  {label:<28} {'found':>6} {'posted':>7} {'seen':>5} {'median':>7} {'best':>6} {f'>={min_views}':>6}"
    lines = [title, head]
    for name, s in stats:
        med = "-" if s["median"] is None else f"{s['median']:g}"
        best = "-" if s["best"] is None else s["best"]
        lines.append(f"  {name:<28} {s['found']:>6} {s['posted']:>7} {s['seen']:>5} {med:>7} {best:>6} {s['reached']:>6}")
    return lines, stats


def _group(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def product_report(p, join, since=None, min_views=50):
    rows = _load(p, join, since)
    head = f"{p.title} Threads yield" + (f" (found since {since})" if since else "")
    if not rows:
        return f"{head}\n  no Threads leads"
    lines, by_query = _table(head + "\n\nBy query", "query",
                             _group(rows, lambda r: threads.query_of(r) or NO_QUERY), join, min_views)
    more, _ = _table("\nBy kind", "kind", _group(rows, kinds.of), join, min_views)
    lines += more
    never = [f"{q} ({s['found']})" for q, s in by_query
             if s["found"] >= NEVER_MIN and not s["posted"] and q != NO_QUERY]
    lines += ["", "Never posted from: " + (", ".join(never) or "none")]
    blind = sum(tsv.status(r) in POSTED and not join.of(r) for r in rows)
    texted = sum(id(r) in join.by_text for r in rows)
    lines.append(f"{blind} posted row(s) have no reply found; {texted} joined by matching the draft text")
    return "\n".join(lines)


def unmatched(join, replies, top=5):
    """Replies no lead in any product points at (self-replies, or leads never
    logged), and the few with the most views."""
    rest = [r for r in replies if r["url"] not in join.used]
    rest.sort(key=lambda r: -(_views(r) or 0))
    lines = [f"{len(rest)} of {len(replies)} replies matched no lead (our own threads, or leads never logged)"]
    lines += [f"  {_views(r) if _views(r) is not None else '-':>6}  {r.get('posted', '')[:10]}  {r['url']}  {r.get('text', '')}"
              for r in rest[:top]]
    return "\n".join(lines)


def report(products, replies_path, since=None, min_views=50, universe=None):
    """`products` are the ones shown; `universe` (default: the same) are the
    ones a reply may join to, so a one-product report doesn't take another
    product's replies for its own or call them unmatched."""
    _, replies = tsv.read(replies_path)
    join = Join(universe or products, replies)
    for p in products:
        join.rows.setdefault(p.name, [])
    parts = []
    if len(products) > 1:
        lines, _ = _table("All products" + (f" (found since {since})" if since else ""), "product",
                          {p.title: _load(p, join, since) for p in products}, join, min_views)
        parts.append("\n".join(lines))
    parts += [product_report(p, join, since, min_views) for p in products]
    parts.append(unmatched(join, replies))
    return ("\n\n" + "-" * 60 + "\n\n").join(parts)
