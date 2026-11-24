"""What's still looking for leads, for the drafts page's "still looking" line.

The drafts page opens as soon as one draft is ready and picks up later drafts by
itself. While something is still looking, the page says what, so a slow source
(Arctic Shift down, say) doesn't hold the whole page back without a word.

Two kinds of entry, one file per product (`<leads>/.looking.json`):
- a process (`leads reddit`), which counts while its pid is alive;
- a session's note (`leads looking "Reading r/Baking threads"`), which counts
  for `ttl` seconds unless it is renewed or cleared with `leads looking --done`.
"""
import json, os, time

SESSION_TTL = 20 * 60


def path(p):
    return p.leads / ".looking.json"


def _read(p):
    try:
        data = json.loads(path(p).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(p, data):
    f = path(p)
    if not data:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(f)


def start(p, key, label, pid=None, ttl=SESSION_TTL):
    data = _read(p)
    data[key] = {"label": label, "pid": pid, "until": None if pid else time.time() + ttl}
    _write(p, data)


def stop(p, key):
    data = _read(p)
    if data.pop(key, None) is not None:
        _write(p, data)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _live(entry):
    if not isinstance(entry, dict) or not entry.get("label"):
        return False
    if entry.get("pid"):
        return _alive(int(entry["pid"]))
    return (entry.get("until") or 0) > time.time()


def current(products, titled=False):
    """Labels of everything still looking, across the page's products."""
    out = []
    for p in products:
        for entry in _read(p).values():
            if _live(entry):
                out.append(f"{p.title}: {entry['label']}" if titled else entry["label"])
    return out
