"""Sales by Eastern day, for the dashboard's Sales tab (Live is in Eastern time too).

`sales.tsv` holds each store's own days. Play's are UTC. Apple's daily report uses the
storefront's regional day: Pacific for the US and Canada, local for Europe, Japan's for
Asia (worked out from a week of sale times, 2026-11-25).

Each sync saves the hour of every recent sale in `hours.json`: iOS from Trends by country
(see live.py), which keeps about 6 report days, and Play from its order times. `rows` then
moves those sales from their store day to their Eastern day. A sale with no saved hour
stays on its store day, so the totals always match the stores' reports.
"""
import json, os, tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import live, mlog

HOURS = mlog.DIR / "hours.json"
ET = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")
REGIONS = {"-100003": ZoneInfo("Europe/Berlin"), "-100004": ZoneInfo("Asia/Tokyo")}
COUNTRIES = {"143460": ZoneInfo("Australia/Sydney"), "143461": ZoneInfo("Pacific/Auckland")}  # assumed, not yet seen at a day's edge
LAG = timedelta(hours=2)    # Trends updates about hourly
REFETCH = timedelta(days=4)  # inside what Trends still keeps: replaced on every sync
IOS_DAYS, PLAY_DAYS, PLAY_FIRST = 8, 14, 150


def _time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def eastern_day(at):
    return _time(at).astimezone(ET).date().isoformat()


def store_day(r):
    """The day the store's own report puts this sale on."""
    zone = timezone.utc if r["store"] == "Play" else COUNTRIES.get(r["country"]) or REGIONS.get(r["region"], PACIFIC)
    return _time(r["at"]).astimezone(zone).date().isoformat()


def through(sales, fetched):
    """The last day the Sales tab shows: the last finished Eastern day with its hours in,
    or the reports' newest day if that's later (the web session has run out)."""
    last = max((r["date"] for r in sales), default="")
    if not fetched:
        return last
    done = (_time(fetched) - LAG).astimezone(ET).date() - timedelta(days=1)
    return max(last, done.isoformat())


def rows(sales, hours, last):
    """sales.tsv's rows with every sale whose hour is known on its Eastern day."""
    total = defaultdict(lambda: [0, 0.0, 0.0])  # (date, app, store): units, proceeds, sales
    reported = defaultdict(str)
    for r in sales:
        t = total[(r["date"], r["app"], r["store"])]
        t[0] += int(r["units"] or 0)
        t[1] += float(r.get("proceeds") or 0)
        t[2] += float(r.get("sales") or 0)
        reported[r["store"]] = max(reported[r["store"]], r["date"])
    known = defaultdict(list)
    for h in hours:
        if h["units"] > 0:
            known[(store_day(h), h["app"], h["store"])].append(h)
    moves = defaultdict(lambda: [0, 0.0, 0.0])
    for key, hs in known.items():
        day, app, store = key
        n, sums = sum(h["units"] for h in hs), [sum(h[k] for h in hs) for k in ("proceeds", "sales")]
        scale = [1.0, 1.0]
        if day <= reported[store]:
            t = total.get(key)
            if not t or n > t[0]:
                continue  # the hours and the report disagree: leave the report's day alone
            # Keep the report's dollars: all of them if every unit is known, else no more than it has.
            scale = [(t[i + 1] / s if n == t[0] else min(1.0, t[i + 1] / s)) if s else 0.0 for i, s in enumerate(sums)]
            t[0] -= n
            for i, s in enumerate(sums):
                t[i + 1] -= s * scale[i]
        for h in hs:
            m = moves[(eastern_day(h["at"]), app, store)]
            m[0] += h["units"]
            m[1] += h["proceeds"] * scale[0]
            m[2] += h["sales"] * scale[1]
    for key, m in moves.items():
        for i in range(3):
            total[key][i] += m[i]
    return [{"date": d, "app": a, "store": s, "units": u, "proceeds": round(p, 4), "sales": round(c, 4)}
            for (d, a, s), (u, p, c) in sorted(total.items()) if d <= last and (u or p > 0.004 or c > 0.004)]


def first_day(hours, store="iOS"):
    """The first whole Eastern day a store's hours cover. Trends keeps whole report days,
    and a US one starts at 3 a.m. Eastern, so it's the day after the first."""
    days = sorted(store_day(h) for h in hours if h["store"] == store)
    return (date.fromisoformat(days[0]) + timedelta(days=1)).isoformat() if days else ""


def parse(result, apps):
    out = []
    for g in result:
        meta = {m.get("dimension"): m for m in g.get("metadata", [])}
        app, place = meta.get("content", {}), meta.get("piano_location", {})
        for d in g.get("data", []):
            out.append({"at": d["hour"], "app": mlog.app_of(app.get("title", "Other"), apps), "store": "iOS",
                        "country": str(place.get("key", "")), "region": str(place.get("parentKey", "")),
                        "units": d.get("units_utc", 0) or 0, "sales": d.get("total_tax_usd_utc", 0) or 0,
                        "proceeds": d.get("Royalty_utc", 0) or 0})
    return out


def ios_hours(apps, now, first):
    top = now.replace(minute=0, second=0, microsecond=0)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    payload = live.body(fmt(top - timedelta(days=IOS_DAYS)), fmt(top))
    payload["measures"].append({"key": "Royalty_utc"})
    payload["group"] = ["content", "piano_location"]
    return parse(live.post(payload, live.with_routing(live.cookies())), apps)


def play_hours(apps, now, first):
    report, why = live.play_orders(24 * (PLAY_FIRST if first else PLAY_DAYS))
    if report is None:
        raise RuntimeError(why)
    return [{"at": o["at"], "app": mlog.app_of(o["title"], apps), "store": "Play", "country": "", "region": "",
             "units": 1, "sales": o["price"], "proceeds": o["net"]} for o in report.get("orders", [])]


def merge(old, new, store, since):
    """Replace `store`'s rows from `since` on; before it, only hours the store still sends."""
    if not new:
        return old
    key = lambda r: (r["at"], r["app"], r["country"])
    fresh = {key(r) for r in new}
    keep = [r for r in old if r["store"] != store or (r["at"] < since and key(r) not in fresh)]
    return sorted(keep + new, key=lambda r: (r["at"], r["store"], r["app"], r["country"]))


def load(path=HOURS):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"fetched": "", "rows": []}


def write(path, data):
    """One row per line, swapped in whole: expired hours can't be fetched again."""
    body = ",\n".join(json.dumps(r, sort_keys=True) for r in data["rows"])
    fd, tmp = tempfile.mkstemp(dir=Path(path).parent, prefix=".hours.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(f'{{"fetched": {json.dumps(data["fetched"])}, "rows": [\n{body}\n]}}\n')
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def sync(apps, path=HOURS, now=None, ios=ios_hours, play=play_hours):
    """Save the newest hours. A store that fails keeps its rows. Returns lines to log."""
    now = now or datetime.now(timezone.utc)
    data, lines = load(path), []
    for store, get in (("iOS", ios), ("Play", play)):
        first = not any(r["store"] == store for r in data["rows"])
        try:
            new = get(apps, now, first)
        except Exception as e:  # noqa: BLE001  logged; the store's own days stand in
            lines.append(f"{store} sale hours: failed, kept the saved ones ({str(e)[:200]})")
            continue
        data["rows"] = merge(data["rows"], new, store, _iso(now - REFETCH))
        if store == "iOS":
            data["fetched"] = _iso(now)
        lines.append(f"{store} sale hours: {len(new)} saved")
    write(path, data)
    return lines
