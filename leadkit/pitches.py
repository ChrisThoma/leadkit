"""leads pitches: roundup authors, app lists, creators and press to pitch, one file per product.

Other people's coverage (a roundup, an app list) can sell more than a hundred
Reddit replies, but pitches written up as prose never get followed up because
nothing says one is due. products/<name>/pitches.tsv is the list and
`leads pitches` says what's next.
"""
import sys
from datetime import date, timedelta

from . import rows, tsv

FIELDS = ["url", "target", "kind", "route", "fit", "status", "sent", "followup", "code", "result", "notes"]
KINDS = {"roundup", "list", "creator", "directory", "press"}
STATUSES = ["todo", "drafted", "sent", "followed-up", "listed", "declined", "no-reply", "skip"]
OUT = {"sent", "followed-up"}
CLOSED = {"listed", "declined", "no-reply", "skip"}
NUDGE = 7


def path(p):
    return p.dir / "pitches.tsv"


def key(url):
    return url.strip().rstrip("/").lower()


def check(values):
    for name, value in values.items():
        name = name.rstrip("+")
        if name not in FIELDS:
            raise SystemExit(f"pitches.tsv has no column {name!r}; it has: {', '.join(FIELDS)}")
        if name == "status" and value not in STATUSES:
            raise SystemExit(f"status must be one of {', '.join(STATUSES)}, not {value!r}")
        if name == "kind" and value and value not in KINDS:
            raise SystemExit(f"kind must be one of {', '.join(sorted(KINDS))}, not {value!r}")


def change(row, values, today):
    """Apply values, then the dates a status change implies, unless the values set them."""
    check(values)
    rows.apply(row, values)
    later = (today + timedelta(days=NUDGE)).isoformat()
    status = values.get("status")
    if status == "sent":
        row["sent"] = values.get("sent") or today.isoformat()
        row["followup"] = values.get("followup") or (date.fromisoformat(row["sent"]) + timedelta(days=NUDGE)).isoformat()
    elif status == "followed-up":
        row["followup"] = values.get("followup") or later
    elif status in CLOSED:
        row["followup"] = ""
    return row


def _find(rs, url):
    return [r for r in rs if key(r.get("url") or "") == key(url)]


def add(p, url, values):
    fields, rs = tsv.read(path(p))
    if _find(rs, url):
        raise SystemExit(f"{url} is already in {path(p)}; use leads pitches set")
    check(values)
    row = dict.fromkeys(fields or FIELDS, "") | {"url": url, "status": "todo"}
    rows.apply(row, values)
    tsv.append(path(p), [row], FIELDS)
    print(f"added: {p.title} pitch: {url}", file=sys.stderr)
    return row


def set_row(p, url, values, today):
    fields, rs = tsv.read(path(p))
    match = _find(rs, url)
    if not match:
        raise SystemExit(f"no pitch for {url} in {path(p)}; add it with leads pitches add")
    for r in match:
        change(r, values, today)
    tsv.write(path(p), fields, rs)
    print(f"set: {p.title} pitch: {url} ({', '.join(values)})", file=sys.stderr)
    return match[0]


def due(rs, today):
    t = today.isoformat()
    return sorted((r for r in rs if tsv.status(r) in OUT and r.get("followup") and r["followup"] <= t),
                  key=lambda r: r["followup"])


def waiting(rs, today):
    late = {id(r) for r in due(rs, today)}
    return [r for r in rs if tsv.status(r) in OUT and id(r) not in late]


def next_up(rs, n):
    return [r for r in rs if tsv.status(r) in ("todo", "drafted")][:n]


def _ago(r, today):
    try:
        return f"sent {r['sent']}, {(today - date.fromisoformat(r['sent'])).days} days ago"
    except ValueError:
        return "sent ?"


def report(p, today, todo=3):
    """Plain text for one product; "" when it has no pitches file."""
    _, rs = tsv.read(path(p))
    if not rs:
        return ""
    lines = [f"{p.title} pitches (products/{p.name}/pitches.tsv)", "  Follow up now"]
    for r in due(rs, today):
        what = "nudge once" if tsv.status(r) == "sent" else "followed up, no answer: mark no-reply, declined or listed"
        lines.append(f"    due {r['followup']}  {r['target']}  {_ago(r, today)}  {what}")
        lines.append(f"      {r.get('route') or 'no route'}  {r['url']}" + (f"  code {r['code']}" if r.get("code") else ""))
    if not due(rs, today):
        lines.append("    none")
    lines.append("  Awaiting a reply")
    lines += [f"    {r['target']}  {_ago(r, today)}, nudge {r.get('followup') or '?'}  {r['url']}"
              for r in waiting(rs, today)] or ["    none"]
    lines.append("  Next to pitch")
    for r in next_up(rs, todo):
        tag = " (drafted)" if tsv.status(r) == "drafted" else ""
        lines.append(f"    {r['target']}{tag}  [{r.get('kind') or '?'}]  {r['url']}")
        for extra in (r.get("route") or "no route", r.get("fit"), r.get("notes")):
            if extra:
                lines.append(f"      {extra}")
    if not next_up(rs, todo):
        lines.append("    none")
    counts = {s: sum(tsv.status(r) == s for r in rs) for s in STATUSES}
    lines.append("  " + ", ".join(f"{s} {n}" for s, n in counts.items() if n))
    return "\n".join(lines)
