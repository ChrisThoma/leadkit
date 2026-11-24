"""The leads TSVs: one row per thread, the record you and the Claude sessions share.

Each file keeps its own header (one product's Threads file may add a column of
its own through threads_row, a Reddit file has `subreddit` and `title`), so rows
are always written back with the header they were read with.
"""
import csv
import os
import tempfile

OPEN = {"", "new", "draft"}


def read(path):
    if not path.exists():
        return None, []
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = []
        for row in reader:
            # Extra cells mean the quoting broke (tab-padded lines inside
            # a multiline reply, say); stop here, before a rewrite can save the damage.
            if None in row:
                raise ValueError(f"{path}: line {reader.line_num} has more columns than the header; "
                                 "fix the file before rewriting it")
            rows.append(row)
        return reader.fieldnames, rows


def write(path, fields, rows):
    """Write to a temp file beside `path` and swap it in, so a write that fails
    partway keeps the old file whole instead of a truncated one."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def rewrite(path, update):
    """Apply update(row) -> bool to every row, saving if any changed. Returns the changed rows."""
    fields, rows = read(path)
    changed = [r for r in rows if update(r)]
    if changed:
        write(path, fields, rows)
    return changed


def append(path, rows, fields):
    """Append rows under the file's own header, or start the file with `fields`."""
    existing, _ = read(path)
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=existing or fields, delimiter="\t", lineterminator="\n",
                           extrasaction="ignore")
        if not existing:
            w.writeheader()
        w.writerows(rows)


def ensure(path, columns):
    """Add any missing columns to the end of the file's header, so older files
    can take the API's post ids without a hand edit."""
    fields, rows = read(path)
    missing = [c for c in columns if fields is not None and c not in fields]
    if missing:
        write(path, fields + missing, [r | dict.fromkeys(missing, "") for r in rows])


def status(r):
    return (r.get("status") or "").strip()
