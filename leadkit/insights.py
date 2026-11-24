"""What the dashboard's numbers say to do: rule-based insights and what's working.

Two things per app, both worked out from the numbers the page already has (no AI):

`insights(app)` compares the last 14 days with the 14 before (and the last 7 with the
weeks before, for spikes) and says in one line what changed and what to look at. Most
apps get 5 to 30 page views a day, so every rule needs enough counts and a change bigger
than chance (two standard errors) before it says anything; quiet weeks give no cards.

`what_works(apps)` is the median lift by post type over the last 90 days, against the
days nothing went out, so a type that only matches an ordinary day doesn't read as a win.

Each insight is {"kind": "down"|"up"|"tip", "text", "hint"}; down first, then up, then tips.
"""
import math, statistics
from collections import defaultdict
from datetime import date, timedelta

from . import dashboard

WINDOW, SPIKE, LOOKBACK = 14, 7, 90
MIN_COUNT = 20      # both windows together, before a count change is worth a line
MIN_VIEWS = 50      # page views (or impressions) in each window, before a rate is
MIN_DAYS = 3        # post days before a type gets a call
ORDER = {"down": 0, "up": 1, "tip": 2}

LABEL = {"impressions": "Impressions", "page_views": "Product page views",
         "downloads": "First-time downloads", "units": "Units sold"}
HINT = {
    ("impressions", "down"): "Impressions are mostly search: check the keyword ranks.",
    ("impressions", "up"): "Check which keywords moved, and keep the listing as it is while they hold.",
    ("page_views", "down"): "Fewer taps from search and from links: check what stopped going out.",
    ("page_views", "up"): "See the posts below for which days carried it.",
    ("downloads", "down"): "",
    ("downloads", "up"): "",
    ("units", "down"): "",
    ("units", "up"): "",
}


def d(s):
    return date.fromisoformat(s)


def last_day(app):
    """The newest day with App Store numbers (posts and sales can run ahead)."""
    ds = [k for k, v in app["days"].items() if v.get("impressions") or v.get("page_views")]
    return max(ds) if ds else None


def first_day(app):
    ds = [k for k, v in app["days"].items() if v.get("impressions") or v.get("page_views")]
    return min(ds) if ds else None


def total(app, end, n, key, back=0):
    """`key` summed over the n days ending `back` days before `end`."""
    out = 0
    for i in range(back, back + n):
        v = app["days"].get((end - timedelta(i)).isoformat(), {})
        out += v.get("units_ios", 0) + v.get("units_play", 0) if key == "units" else v.get(key, 0)
    return out


def counts_differ(now, before):
    """Two counts over equal spans: a real change, not chance (Poisson, two standard errors)."""
    if now + before < MIN_COUNT or not before:
        return False
    return abs(now - before) / math.sqrt(now + before) >= 2 and abs(now / before - 1) >= 0.2


def rates_differ(k1, n1, k0, n0):
    """k1/n1 against k0/n0: a real change (two-proportion z, two standard errors)."""
    if min(n1, n0) < MIN_VIEWS or not (k1 + k0):
        return False
    p = (k1 + k0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    return se > 0 and abs(k1 / n1 - k0 / n0) / se >= 2


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b and a / b < 0.1 else f"{100 * a / b:.0f}%" if b else "–"


def change(now, before):
    c = round(100 * (now / before - 1))
    return f"{'+' if c > 0 else ''}{c}%"


def counts(app, end):
    out = []
    for key in ("impressions", "page_views", "downloads", "units"):
        now, before = total(app, end, WINDOW, key), total(app, end, WINDOW, key, WINDOW)
        if counts_differ(now, before):
            kind = "up" if now > before else "down"
            out.append({"kind": kind, "text": f"{LABEL[key]} {change(now, before)}: {now:,} in the last 14 days, {before:,} in the 14 before.",
                        "hint": HINT[(key, kind)]})
    return out


def rates(app, end):
    out = []
    t = lambda k, back=0: total(app, end, WINDOW, k, back)
    imp1, imp0, pv1, pv0, dl1, dl0 = t("impressions"), t("impressions", WINDOW), t("page_views"), t("page_views", WINDOW), t("downloads"), t("downloads", WINDOW)
    if rates_differ(pv1, imp1, pv0, imp0):
        kind = "up" if pv1 / imp1 > pv0 / imp0 else "down"
        hint = ("What search shows decides this: the icon, title, subtitle and first screenshots." if kind == "down"
                else "Whatever changed in the icon, title or first screenshots is working.")
        if kind == "down" and imp1 >= 1.5 * imp0:
            # New impressions from broader searches tap less: the rate falls with nothing wrong.
            kind, hint = "tip", f"Mostly because impressions grew {change(imp1, imp0).lstrip('+')}: people on broader searches tap less. Page views still went {'up' if pv1 > pv0 else 'down'} {change(pv1, pv0).lstrip('+-')}."
        out.append({"kind": kind, "text": f"Tap-through {pct(pv0, imp0)} → {pct(pv1, imp1)}: the share of impressions that opened the page.", "hint": hint})
    if rates_differ(dl1, pv1, dl0, pv0):
        kind = "up" if dl1 / pv1 > dl0 / pv0 else "down"
        out.append({"kind": kind, "text": f"Page conversion {pct(dl0, pv0)} → {pct(dl1, pv1)}: the share of page views that downloaded.",
                    "hint": "The page itself: screenshots, description, price, ratings. Check what changed around when it fell." if kind == "down" else "The page is converting better: keep what changed on it."})
    return out


def spikes(app, end):
    """A source or a country well above its usual week: something sent people there."""
    out = []
    weeks = (end - d(first_day(app))).days // 7
    if weeks < 2:
        return out
    base_weeks = min(4, weeks - 1)
    for src in dashboard.SOURCES:
        now = total(app, end, SPIKE, "pv:" + src)
        usual = total(app, end, SPIKE * base_weeks, "pv:" + src, SPIKE) / base_weeks
        if now >= 15 and now >= 3 * max(usual, 1):
            where = top_country(app, end)
            what = {"App Store browse": "maybe featured or in a chart", "Web referrer": "a link outside the App Store is sending people",
                    "App referrer": "an app (Threads, Reddit, Instagram) is sending people", "App Store search": "a keyword moved"}[src]
            out.append({"kind": "up", "text": f"{src} page views {now} in the last 7 days, about {usual:.0f} in a usual week: {what}{f', mostly {where}' if where else ''}.",
                        "hint": "Find what caused it while it's fresh, and do more of it."})
    return out


def top_country(app, end):
    """The country with most of the last week's rise in page views, if one has most of it."""
    rise = defaultdict(int)
    for i in range(SPIKE):
        for c, m in app.get("countries", {}).get((end - timedelta(i)).isoformat(), {}).items():
            rise[c] += m.get("page_views", 0)
        for c, m in app.get("countries", {}).get((end - timedelta(i + SPIKE)).isoformat(), {}).items():
            rise[c] -= m.get("page_views", 0)
    up = {c: v for c, v in rise.items() if v > 0}
    if not up:
        return ""
    c, v = max(up.items(), key=lambda x: x[1])
    return country_name(c) if v >= 0.5 * sum(up.values()) and len(up) > 1 else ""


def country_name(code):
    return {"US": "the US", "GB": "the UK", "AE": "the UAE", "NL": "the Netherlands", "PH": "the Philippines"}.get(code, code)


# ---- what's working ----------------------------------------------------------

def day_lifts(app, end, lookback=LOOKBACK):
    """{day: (after, base)} for every day in the lookback whose day after is in the data."""
    start, first = end - timedelta(lookback - 1), d(first_day(app))
    out = {}
    for i in range(lookback):
        day = start + timedelta(i)
        # The day after has to be in, and the week before too, or the lift means nothing.
        if day + timedelta(1) > end or day - timedelta(7) < first:
            continue
        out[day.isoformat()] = dashboard.lift(app["days"], day.isoformat())
    return out


def ratio(after, base):
    return after / base if base else None


def median(xs):
    return statistics.median(xs) if xs else None


def what_works(apps, lookback=LOOKBACK):
    """Rows by post type, best first, and the nothing-posted baseline, over the lookback.

    Each row: type, days (post days in the lookback), lift (median page-view lift on
    those days), extra (median page views over usual), alone (days it was the only type
    out) and alone_lift, downloads (median downloads that day and the next), call."""
    per, quiet, quiet_dl = defaultdict(list), [], []
    for app in apps:
        end = last_day(app)
        if not end:
            continue
        lifts = day_lifts(app, d(end), lookback)
        types = defaultdict(set)
        for p in app["posts"]:
            types[p["date"]].add(p["type"])
        for day, (after, base) in lifts.items():
            dl = app["days"].get(day, {}).get("downloads", 0) + app["days"].get((d(day) + timedelta(1)).isoformat(), {}).get("downloads", 0)
            if not types.get(day):
                quiet.append((after, base))
                quiet_dl.append(dl)
                continue
            for t in types[day]:
                per[t].append((after, base, dl, len(types[day]) == 1))
    if not per:
        return {"rows": [], "baseline": None}
    q = median([r for r in (ratio(a, b) for a, b in quiet) if r is not None])
    rows = []
    for t, xs in per.items():
        lift = median([r for r in (ratio(a, b) for a, b, *_ in xs) if r is not None])
        alone = [x for x in xs if x[3]]
        alone_lift = median([r for r in (ratio(a, b) for a, b, *_ in alone) if r is not None])
        rows.append({"type": t, "days": len(xs), "lift": lift, "extra": median([a - b for a, b, *_ in xs]),
                     "alone": len(alone), "alone_lift": alone_lift if len(alone) >= MIN_DAYS else None,
                     "downloads": median([x[2] for x in xs]), "call": call(lift, len(xs), q)})
    rows.sort(key=lambda r: (r["call"] == "too few", -(r["lift"] or 0)))
    base = {"days": len(quiet), "lift": q, "downloads": median(quiet_dl)} if quiet else None
    return {"rows": [round_row(r) for r in rows], "baseline": base and round_row(base)}


def call(lift, days, quiet):
    """keep, weak or mixed against an ordinary day; too few under MIN_DAYS."""
    if days < MIN_DAYS or lift is None:
        return "too few"
    # Above an ordinary week before (×1.2) and clearly above the days nothing went out.
    if lift >= 1.2 and lift >= (quiet or 0) * 1.25:
        return "keep"
    if lift <= 1.05 and days >= 5:
        return "weak"
    return "mixed"


def round_row(r):
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()}


def posting(app, end, works):
    """Nothing has gone out for a while, and a type has been lifting: say so."""
    made = [p["date"] for p in app["posts"] if not p["type"].endswith(" reply")]
    if not made:
        return []
    gap = (end - d(max(made))).days
    keep = [r for r in works["rows"] if r["call"] == "keep" and not r["type"].endswith(" reply")]
    if gap < 4 or not keep:
        return []
    best = keep[0]
    return [{"kind": "tip", "text": f"Nothing posted in {gap} days. {plural(best['type'])} lifted page views ×{best['lift']:.1f} on a median day ({best['days']} days).",
             "hint": ""}]


def plural(t):
    return t[:-1] + "ies" if t.endswith("y") else t + "s"


def standouts(app, end, works):
    """The one post day in the last 14 that lifted most, if it beat a usual day clearly."""
    days, first = defaultdict(list), d(first_day(app))
    for p in app["posts"]:
        # The day after is in, and so is the week before (no "against 0" in launch week).
        if (end - timedelta(WINDOW)).isoformat() < p["date"] < end.isoformat() and d(p["date"]) - timedelta(7) >= first:
            days[p["date"]].append(p)
    best, top = None, 0
    for day, ps in days.items():
        after, base = dashboard.lift(app["days"], day)
        if after >= 15 and after >= 2 * max(base, 1) and after - base > top:
            best, top = (day, ps, after, base), after - base
    if not best:
        return []
    day, ps, after, base = best
    made = [p for p in ps if not p["type"].endswith(" reply")] or ps
    n = defaultdict(int)
    for p in made:
        n[p["type"]] += 1
    what = ", ".join(f"{k} {plural(t)}" if k > 1 else f"{'an' if t[0] in 'AEIOX' else 'a'} {t}" for t, k in sorted(n.items(), key=lambda x: -x[1]))
    when = d(day).strftime("%a %b ") + str(d(day).day)
    return [{"kind": "up", "text": f"{when}: {what} took page views to {after} over two days, against {round(base)} usual.",
             "hint": "The best day of the last two weeks. Worth another one like it."}]


def insights(app, works=None):
    """The app's insight lines, worst first."""
    end = last_day(app)
    if not end:
        return []
    e, first = d(end), d(first_day(app))
    works = works or what_works([app])
    out = []
    if (e - first).days + 1 >= 2 * WINDOW:  # both windows inside the data
        out += counts(app, e) + rates(app, e)
    out += spikes(app, e) + standouts(app, e, works) + posting(app, e, works)
    return sorted(out, key=lambda x: ORDER[x["kind"]])
