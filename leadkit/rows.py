"""leads set: change one lead row, or add one, through the tsv module.

Replies span several lines inside quotes, so a leads file can't be edited by
splitting it on newlines without breaking its rows. Sessions skipping a thread, logging
an F5Bot find or saving a draft go through here instead.
"""
import re, sys
from datetime import date
from urllib.parse import urlsplit

from . import kinds, reddit, threads, tsv

STATUSES = tsv.OPEN | {"skip", "posted"}
KINDS = {kinds.DOMAIN, kinds.APP_KIND}


def platform(url):
    host = urlsplit(url).netloc.lower()
    if host == "redd.it" or host.endswith("reddit.com"):
        return "Reddit"
    if host.endswith(("threads.com", "threads.net")):
        return "Threads"
    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        return "X"
    raise SystemExit(f"{url} isn't a Reddit, Threads or X link")


def key(url):
    """The same thread whatever the host, query or trailing slash."""
    parts = urlsplit(url.strip())
    return f"{platform(url)}:{parts.path.rstrip('/').lower()}"


def check(fields, values, path):
    for name, value in values.items():
        name = name.rstrip("+")
        if name not in fields:
            raise SystemExit(f"{path.name} has no column {name!r}; it has: {', '.join(fields)}")
        if name == "status" and value not in STATUSES:
            allowed = ", ".join(sorted(s or "''" for s in STATUSES))
            raise SystemExit(f"status must be one of {allowed}, not {value!r}")
        if name == "kind" and value not in KINDS:
            raise SystemExit(f"kind must be {' or '.join(sorted(KINDS))}, not {value!r}")


def parse(pairs, stdin=None):
    """field=value pairs to {field: value}; field+=value keeps its + for apply, value - reads stdin."""
    values = {}
    for pair in pairs:
        name, eq, value = pair.partition("=")
        if not eq or not name:
            raise SystemExit(f"expected field=value or field+=value, got {pair!r}")
        values[name] = (stdin or sys.stdin).read().rstrip("\n") if value == "-" else value
    return values


def apply(row, values):
    for name, value in values.items():
        if name.endswith("+"):
            name = name[:-1]
            value = f"{row.get(name) or ''} {value}".strip()
        row[name] = value


def set_row(p, url, values, add=False):
    """Set `values` ({field: value}; a key ending in + appends) on the row for `url`.
    With add, a thread not in the file yet gets a new row, which needs a kind."""
    where = platform(url)
    path = p.tsv_for(where)
    fields, rows = tsv.read(path)
    if fields and where != "Reddit" and "query" not in fields and any(k.rstrip("+") == "query" for k in values):
        tsv.ensure(path, ["query"])  # older Threads and X files predate the column
        fields, rows = tsv.read(path)
    fields = fields or (reddit.FIELDS if where == "Reddit" else threads.FIELDS)
    check(fields, values, path)
    want = key(url)
    match = [r for r in rows if r.get("url") and key(r["url"]) == want]
    if match:
        for r in match:
            apply(r, values)
        tsv.write(path, fields, rows)
        row = match[0]
    elif not add:
        raise SystemExit(f"no {where} row for {url} in {path}; pass --add to log a new thread")
    else:
        if "kind" not in values:
            raise SystemExit("a new row needs kind=app or kind=domain")
        row = dict.fromkeys(fields, "") | {"found": date.today().isoformat(), "url": url, "status": "new"}
        sub = re.match(r"/r/([^/]+)", urlsplit(url).path)
        if where == "Reddit" and sub and "subreddit" in fields:
            row["subreddit"] = sub.group(1)
        apply(row, values)
        path.parent.mkdir(parents=True, exist_ok=True)
        tsv.append(path, [row], fields)
    tsv.read(path)  # raises if the file no longer parses
    print(f"{'added' if not match else 'set'}: {p.title} {where}: {url} ({', '.join(values)})", file=sys.stderr)
    return row
