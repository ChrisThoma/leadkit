"""Live units and sales: the last 24 hours, by hour and by app, from App Store Connect's Trends.

The official API's sales reports are daily and a day late. The only near-live numbers
are on App Store Connect's Trends page (Sales > Units, period Hour), which updates
about hourly. That page reads an internal endpoint, `.../vcubes/778/timeseries`, with
a body like
    {"interval": {"key": "hour", "startDate": ISO, "endDate": ISO},
     "measures": [{"key": "units_utc"}, {"key": "total_tax_usd_utc"}],
     "filters": [], "group": ["content"]}
(found 2026-11-21; `total_tax_usd_utc` is the page's "Sales", customer price in USD).

Google Play has nothing hourly. Its sales report (`play-sales --orders`) lists each
order with the second it was charged, but Google rewrites the report only a few times a
day, so orders after its last update (`play_updated`) are missing though Play Console's
Order management already shows them. Play orders
are merged into the same app's hours, counted apart as `play` so the page can split them.

It needs an App Store Connect web session, the one `asc web auth login` keeps. Each
call exports the session to a 0600 temp file, reads the cookies and deletes the file.
When the session has run out, `fetch` raises SignedOut and the page says to sign in.
"""
import json, os, subprocess, tempfile, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

URL = ("https://appstoreconnect.apple.com/trends/gsf/salesTrendsApp/businessareas/"
       "InternetServices/subjectareas/iTunes/vcubes/778/timeseries")
MEASURES = ("units_utc", "total_tax_usd_utc")


class SignedOut(Exception):
    pass


def cookies(run=subprocess.run):
    """The session's appstoreconnect.apple.com cookies as one Cookie header."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        out = run(["asc", "web", "auth", "export", "--output-path", path, "--overwrite"],
                  capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise SignedOut((out.stderr or out.stdout).strip()[:200] or "no web session")
        bundle = json.loads(Path(path).read_text())
    finally:
        Path(path).unlink(missing_ok=True)
    jar = [c for c in bundle.get("cookies", []) if "appstoreconnect.apple.com" in c.get("url", "")]
    if not jar:
        raise SignedOut("the web session has no App Store Connect cookies")
    return "; ".join(f"{c['name']}={c['value']}" for c in jar)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def with_routing(cookie, open_=None):
    """The session plus the routing cookies Trends sets on its first answer.

    Trends answers a request without its `dc` cookie with a 302 to /login, even with a good
    session (found 2026-11-21: olympus accepted the same cookies). That 302 sets `dc`; the
    same request with it goes through."""
    open_ = open_ or urllib.request.build_opener(_NoRedirect).open
    req = urllib.request.Request("https://appstoreconnect.apple.com/trends/sales", headers={"Cookie": cookie})
    try:
        resp = open_(req, timeout=30)
    except urllib.error.HTTPError as e:
        resp = e
    extra = [v.split(";")[0] for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    names = {c.split("=")[0] for c in extra}
    kept = [c for c in cookie.split("; ") if c.split("=")[0] not in names]
    return "; ".join(kept + extra + ["POD=us~en"])


def window(now=None, hours=24):
    """(start, end) ISO strings for the last `hours` whole hours, as the Trends page asks."""
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return iso(start), iso(now - timedelta(hours=1))


def body(start, end):
    return {"interval": {"key": "hour", "startDate": start, "endDate": end},
            "measures": [{"key": m} for m in MEASURES], "filters": [], "group": ["content"]}


def post(payload, cookie, opener=None):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "Cookie": cookie,
        "Origin": "https://appstoreconnect.apple.com",
        "Referer": "https://appstoreconnect.apple.com/trends/sales"})
    opener = opener or urllib.request.build_opener(_NoRedirect).open
    try:
        with opener(req, timeout=60) as r:
            text = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 401, 403):
            raise SignedOut(f"App Store Connect said {e.code}") from e
        raise
    if text.lstrip().startswith("<"):  # a sign-in page instead of JSON
        raise SignedOut("App Store Connect sent its sign-in page")
    data = json.loads(text)
    if data.get("status") != "success":
        raise RuntimeError(f"Trends: {data.get('error')}")
    return data["result"]


def parse(result):
    """[{"id", "title", "hours": {iso hour: {"units", "sales"}}}] from one grouped response."""
    apps = []
    for group in result:
        meta = (group.get("metadata") or [{}])[0]
        hours = {}
        for row in group.get("data", []):
            h = hours.setdefault(row["hour"], {"units": 0, "sales": 0.0})
            h["units"] += row.get("units_utc", 0) or 0
            h["sales"] += row.get("total_tax_usd_utc", 0) or 0
        apps.append({"id": str(meta.get("key", "")), "title": meta.get("title", "Other"),
                     "platform": meta.get("supportedPlatformName", ""), "hours": hours})
    return apps


def play_sales():
    """The play-sales command, found even when PATH lacks it."""
    from .mlog import tool
    return tool("play-sales")


def play_orders(hours=48, run=subprocess.run):
    """({"updated": when Google last rewrote its report, "orders": [...]}, "") for the last
    `hours`, or (None, why) if play-sales failed."""
    try:
        out = run([play_sales(), "--orders", str(hours)], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)[:200]
    if out.returncode:
        return None, (out.stderr or out.stdout).strip()[-200:]
    return json.loads(out.stdout or "{}"), ""


def add_play(apps, orders, start, end, names):
    """Fold Play orders into `apps` (one fetch's list): hours start..end count as now,
    the 24 before as prev. An app Play sold that Apple didn't gets its own row."""
    from . import mlog  # the store titles to app names ("Proofer: temporizador de masa")
    s, e = start[:13], end[:13]
    ps = (datetime.strptime(s, "%Y-%m-%dT%H") - timedelta(hours=24)).strftime("%Y-%m-%dT%H")
    by = {mlog.app_of(a["title"], names): a for a in apps}
    for o in orders:
        hour = o["at"][:13]
        if not ps <= hour <= e:
            continue
        name = mlog.app_of(o["title"], names)
        a = by.get(name)
        if a is None:
            a = by[name] = {"id": "play:" + name, "title": name, "platform": "Android", "hours": {}, "prev_units": 0, "prev_sales": 0.0}
            apps.append(a)
        a.setdefault("play_units", 0)
        a.setdefault("prev_play_units", 0)
        if hour >= s:
            h = a["hours"].setdefault(hour + ":00:00Z", {"units": 0, "sales": 0.0})
            h["units"] += 1
            h["sales"] = round(h["sales"] + o["sales"], 2)
            h["play"] = h.get("play", 0) + 1
            a["play_units"] += 1
        else:
            a["prev_units"] += 1
            a["prev_sales"] = round(a["prev_sales"] + o["sales"], 2)
            a["prev_play_units"] += 1
    return apps


def fetch(now=None, cookie=None, opener=None, play=None, names=None):
    """The last 24 hours and the 24 before them, by app and hour."""
    cookie = cookie or with_routing(cookies())
    now = now or datetime.now(timezone.utc)
    s, e = window(now)
    ps, pe = window(now - timedelta(hours=24))
    current = parse(post(body(s, e), cookie, opener))
    previous = parse(post(body(ps, pe), cookie, opener))
    before = {a["id"]: a for a in previous}
    for a in current:
        p = before.pop(a["id"], {"hours": {}})
        a["prev_units"] = sum(h["units"] for h in p["hours"].values())
        a["prev_sales"] = round(sum(h["sales"] for h in p["hours"].values()), 2)
    for a in before.values():  # sold the day before, nothing since
        current.append({**a, "hours": {}, "prev_units": sum(h["units"] for h in a["hours"].values()),
                        "prev_sales": round(sum(h["sales"] for h in a["hours"].values()), 2)})
    report, why = play if play is not None else play_orders()
    orders = (report or {}).get("orders", [])
    if orders:
        if names is None:
            from . import product
            names = [p.title for p in product.everything()]
        add_play(current, orders, s, e, names)
    return {"start": s, "end": e, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "apps": current,
            "play_error": why, "play_updated": (report or {}).get("updated", "")}


_cache = {}


def cached(max_age=300):
    """fetch(), at most once per `max_age` seconds; errors come back as {"error": ...}."""
    if _cache.get("at", 0) > time.time() - max_age:
        return _cache["data"]
    try:
        data = fetch()
    except SignedOut as e:
        data = {"error": "signed_out", "detail": str(e)}
    except Exception as e:  # noqa: BLE001  the page shows it; the server keeps going
        data = {"error": "failed", "detail": str(e)[:300]}
    if "error" not in data:
        _cache.update(at=time.time(), data=data)
    return data
