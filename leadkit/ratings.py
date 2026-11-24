"""Star ratings per app on each store, for the dashboard's Ratings tab.

App Store: `asc reviews ratings --all` gives each app's average and count across every
storefront, counting stars left without text. Google Play: `play-sales --ratings` reads
the reviews export in the Play report bucket, which holds every star rating, with text
or without (Play's API and its ratings stats files have no count). Both are saved to
marketing/ratings.json ("apps" by App Store id, "play" by package) so the page and the
written-out file have the last copy.
"""
import json, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import mlog

STORE = mlog.DIR / "ratings.json"


def rating(app_id, run=subprocess.run):
    """{"avg", "count"} for one app; an app with no ratings anywhere is 0 and 0."""
    out = run(["asc", "reviews", "ratings", "--app", app_id, "--all"], capture_output=True, text=True, timeout=120)
    if out.returncode:
        why = (out.stderr or out.stdout).strip()
        if "not found in any country" in why:
            return {"avg": 0, "count": 0}
        raise RuntimeError(why[:200])
    r = json.loads(out.stdout or "{}")
    return {"avg": round(r.get("averageRating") or 0, 2), "count": r.get("totalCount") or 0}


def play_ratings(run=subprocess.run):
    """{package: {"avg", "count"}} from `play-sales --ratings`."""
    from .live import play_sales
    out = run([play_sales(), "--ratings"], capture_output=True, text=True, timeout=180)
    if out.returncode:
        raise RuntimeError(((out.stderr or out.stdout).strip() or "play-sales failed")[:200])
    return json.loads(out.stdout or "{}")


def play_title(package, titles):
    """The App Store title of a Play package's app (com.example.proofer is the one
    whose title starts "Proofer"), else its last part, capitalised."""
    tail = package.rsplit(".", 1)[-1].lower()
    return next((t for t in titles if t.split(":")[0].split()[0].lower() == tail), tail.capitalize())


def load(path=STORE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"fetched": "", "apps": {}}


def fetch(app_list, path=STORE, get=rating, now=None, play=None):
    """Every app's rating, saved to `path`. An app that fails keeps its saved numbers.
    `play` (play_ratings) adds Google Play's; without it the saved Play numbers stay."""
    saved, errors = load(path), []

    def one(item):
        app_id, title = item
        try:
            got = get(app_id)
            old = saved["apps"].get(app_id, {})
            if not got["count"] and old.get("count"):
                # Apple's lookup sometimes answers 0 for an app with ratings (and the real
                # count a minute later), so a drop to nothing keeps the saved numbers.
                return app_id, {**old, "title": title}
            return app_id, {"title": title, **got}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{title.split(':')[0]}: {str(e)[:150]}")
            return app_id, saved["apps"].get(app_id, {"title": title, "avg": 0, "count": 0})

    with ThreadPoolExecutor(6) as pool:
        apps = dict(pool.map(one, app_list))
    play_saved = saved.get("play", {})
    if play:
        try:
            titles = [t for _, t in app_list]
            play_saved = {pkg: {"title": play_title(pkg, titles), **r} for pkg, r in play().items()}
        except Exception as e:  # noqa: BLE001
            errors.append(f"Google Play: {str(e)[:150]}")
    out = {"fetched": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "apps": apps, "play": play_saved}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out | {"errors": errors}


_lock = threading.Lock()
_last = {"at": 0.0, "errors": []}


def cached(app_list, max_age=1800, path=STORE):
    """The saved ratings, fetched again first if the last fetch is older than `max_age`."""
    with _lock:
        if time.time() - _last["at"] > max_age:
            try:
                _last.update(at=time.time(), errors=fetch(app_list, path, play=play_ratings).get("errors", []))
            except Exception as e:  # noqa: BLE001  the page shows the saved copy and why
                _last.update(at=time.time(), errors=[str(e)[:200]])
        return load(path) | {"errors": _last["errors"]}
