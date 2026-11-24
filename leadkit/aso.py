"""App Store keyword tracking: where a product ranks for its keywords, how
searched each keyword is, and how hard it is to rank for.

Three public sources, none needing a login:

- The store's own search, from the server-rendered apps.apple.com search page
  (`/<country>/iphone/search?term=`). This is Apple's real ranking, but the page
  only carries the top 12, so anything lower reads ">12".
- The iTunes Search API (`itunes.apple.com/search`), which goes 200 deep but is a
  separate index that only loosely tracks the store: on 2026-10-27 the two agreed
  on most of the top 12 for a keyword but not on the order.
- The store's typing suggestions (MZSearchHints). How few letters it takes before
  Apple suggests a phrase is the popularity signal: Apple shows no search counts
  outside Search Ads, and this is the same signal paid ASO tools build theirs on.

Difficulty comes from the median rating count of the API's top 10, so a keyword
held by apps with thousands of ratings scores high. Both scores are estimates,
not Apple figures.

Each check appends one row per keyword to products/<name>/aso/ranks.tsv, so the
history builds up for comparing against App Analytics and metadata changes.
"""
import html, json, math, plistlib, re, statistics, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import product, tsv

FIELDS = ["date", "country", "keyword", "store_rank", "api_rank", "popularity", "typed", "difficulty",
          "top10_median_ratings", "leader", "ahead"]
STORE_DEPTH = 12
API_LIMIT = 200
# The Search API allows about 20 calls a minute.
API_PAUSE = 3.1
HINT_PAUSE = 0.3
STORE_PAUSE = 1.0
# Phrases ranked in each of a product's ASO_COUNTRIES, the most valuable first. Each costs a
# Search API call (about 4 s), and 15 keeps the daily run under half an hour.
COUNTRY_PHRASES = 15
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
# The hints endpoint takes the storefront from this header, not a parameter.
# Each was checked on 2026-10-27 against its suggestions for "ba" (local banks).
STOREFRONTS = {
    "us": 143441, "gb": 143444, "au": 143460, "ca": 143455, "ie": 143449, "nz": 143461, "de": 143443,
    "at": 143445, "ch": 143459, "fr": 143442, "be": 143446, "es": 143454, "mx": 143468, "br": 143503,
    "pt": 143453, "it": 143450, "nl": 143452, "se": 143456, "no": 143457, "dk": 143458, "fi": 143447,
    "pl": 143478, "cz": 143489, "sk": 143496, "hu": 143482, "ro": 143487, "gr": 143448, "tr": 143480,
    "ru": 143469, "ua": 143492, "jp": 143462, "kr": 143466, "cn": 143465, "tw": 143470, "hk": 143463,
    "th": 143475, "vn": 143471, "id": 143476, "my": 143473, "in": 143467, "sa": 143479, "ae": 143481,
    "il": 143491, "hr": 143494, "si": 143499,
}


def fetch(url, headers=None, pause=0.0):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            time.sleep(pause)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"  {e.code}, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  {e.code} for {url}", file=sys.stderr)
            return None
        except Exception as e:  # a network blip loses one keyword, not the run
            print(f"  {e} for {url}", file=sys.stderr)
            return None
    return None


# Sources

def api_results(data):
    return [{"id": r["trackId"], "name": r.get("trackName", ""), "ratings": r.get("userRatingCount", 0),
             "price": r.get("price", 0)} for r in json.loads(data).get("results", []) if "trackId" in r]


def api_search(term, country, limit=API_LIMIT):
    q = urllib.parse.urlencode({"term": term, "entity": "software", "country": country, "limit": limit})
    data = fetch(f"https://itunes.apple.com/search?{q}", pause=API_PAUSE)
    return api_results(data) if data else None


def store_results(page):
    """App IDs and names in result order from an apps.apple.com search page."""
    out, seen = [], set()
    for slug, app_id in re.findall(r'href="[^"]*/app/([^/"]+)/id(\d+)', page):
        if int(app_id) not in seen:
            seen.add(int(app_id))
            out.append({"id": int(app_id), "name": slug.replace("-", " ")})
    return out


def store_search(term, country):
    q = urllib.parse.quote(term)
    data = fetch(f"https://apps.apple.com/{country}/iphone/search?term={q}", pause=STORE_PAUSE)
    return store_results(html.unescape(data.decode("utf-8", "replace"))) if data else None


def hint_terms(data):
    return [h["term"].lower() for h in plistlib.loads(data).get("hints", [])]


def hints(prefix, country, cache):
    if prefix not in cache:
        q = urllib.parse.urlencode({"clientApplication": "Software", "term": prefix})
        front = STOREFRONTS[country]
        data = fetch(f"https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints?{q}",
                     headers={"X-Apple-Store-Front": f"{front}-1,29"}, pause=HINT_PAUSE)
        if not data:  # rate-limited or down: unknown, so don't remember it as unsuggested
            return []
        cache[prefix] = hint_terms(data)
    return cache[prefix]


# Scores

def typed_letters(term, country, cache, matches=None):
    """How many letters of the term are typed before Apple suggests it, or None.
    `matches(term, suggestions)` loosens what counts; by default only the exact phrase."""
    term = term.lower()

    def shown(n):
        found = hints(term[:n], country, cache)
        return matches(term, found) if matches else term in found

    # Most phrases are never suggested, so the whole phrase goes first and one
    # request settles them; typing letter by letter cost ~20 each and drew 429s.
    if len(term) < 2 or not shown(len(term)):
        return None
    # Then bisect: suggestions narrow as letters are added, so a phrase shown
    # at some prefix stays shown at the longer ones.
    lo, hi = 2, len(term)
    while lo < hi:
        mid = (lo + hi) // 2
        if shown(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def popularity(typed):
    # Absolute letters, not a share of the phrase: a phrase people search gets
    # suggested early however long it is. 2 letters reads 100, 3 reads 85,
    # 5 reads 61, 8 reads 38, 12 reads 20.
    if typed is None:
        return 0
    return max(1, round(100 * 0.85 ** (typed - 2)))


def difficulty(results):
    top = [r["ratings"] for r in (results or [])[:10]]
    if not top:
        return 0, 0
    median = statistics.median(top)
    # 10 ratings reads 26, 100 reads 50, 1,000 reads 75, 10,000 and up reads 100.
    return min(100, round(25 * math.log10(1 + median))), round(median)


def rank(results, app_id, depth=None):
    if results is None:
        return ""
    for i, r in enumerate(results, 1):
        if r["id"] == app_id:
            return str(i)
    return f">{depth or len(results)}"


def ahead(results, app_id, competitors):
    """Tracked competitors ranked above the app (all of them that rank, if it doesn't)."""
    names = {v: k for k, v in competitors.items()}
    out = []
    for r in results or []:
        if r["id"] == app_id:
            break
        if r["id"] in names:
            out.append(names[r["id"]])
    return ", ".join(out)


# Records

def tsv_path(p):
    return p.dir / "aso" / "ranks.tsv"


def config(p):
    return int(p.need("APP_STORE_ID")), p.need("ASO_KEYWORDS"), p.get("ASO_COMPETITORS", {})


def keywords(p, country="us"):
    """What to rank in a storefront: ASO_KEYWORDS, except in one of the product's ASO_COUNTRIES,
    where it's the phrases `aso locales` packed into that language's field (English stores reuse
    ASO_KEYWORDS), cut to COUNTRY_PHRASES."""
    from . import aso_locales  # it imports this module
    english = p.need("ASO_KEYWORDS")
    if country not in (p.get("ASO_COUNTRIES") or []):
        return english
    if not localized(p, country):
        return english[:COUNTRY_PHRASES]
    return aso_locales.targeted(p, aso_locales.locale_for(country), COUNTRY_PHRASES)


def localized(p, country):
    from . import aso_locales
    locale = aso_locales.locale_for(country)
    return country in (p.get("ASO_COUNTRIES") or []) and bool(locale) and not locale.startswith("en-")


def check_keyword(term, app_id, competitors, country, cache, with_hints=True):
    # The store page and the hints are other hosts with their own limits, so they run while
    # the Search API call and its pause do: per keyword, about 4 s instead of 6 or more.
    with ThreadPoolExecutor(1) as pool:
        side = pool.submit(lambda: (store_search(term, country),
                                    typed_letters(term, country, cache) if with_hints else None))
        api = api_search(term, country)
        store, typed = side.result()
    names = {r["id"]: r["name"] for r in api or []}
    level, median = difficulty(api)
    leader = (store or api or [{}])[0]
    store_rank = rank(store, app_id, STORE_DEPTH)
    return {
        "date": date.today().isoformat(), "country": country, "keyword": term,
        "store_rank": store_rank, "api_rank": rank(api, app_id, API_LIMIT),
        "popularity": str(popularity(typed)) if with_hints else "", "typed": str(typed or "") if with_hints else "",
        "difficulty": str(level), "top10_median_ratings": str(median),
        "leader": names.get(leader.get("id"), leader.get("name", "")),
        # The store's order where the app is in its top 12, the API's past that.
        "ahead": ahead(store if store_rank.isdigit() else api, app_id, competitors),
    }


def check(p, country="us", only=None, with_hints=True, save=True):
    app_id, _, competitors = config(p)
    terms = only or keywords(p, country)
    if not terms:
        print(f"{p.title}, {country}: no phrases to rank; run `aso locales -p {p.name}` for its language",
              file=sys.stderr)
        return []
    # Apple's suggestions in another language rarely hold a whole phrase, so the exact match
    # here reads 0; locale-keywords.tsv has aso locales' looser popularity for these.
    with_hints = with_hints and not localized(p, country)
    previous = latest(p, country)
    cache, rows = {}, []
    for term in terms:
        print(f"  {term}", file=sys.stderr)
        rows.append(check_keyword(term, app_id, competitors, country, cache, with_hints=with_hints))
    if save:
        path = tsv_path(p)
        path.parent.mkdir(exist_ok=True)
        tsv.append(path, rows, FIELDS)
    print(table(p, rows, previous))
    return rows


def latest(p, country="us", before=None):
    """The newest saved row per keyword, optionally from before a date."""
    _, rows = tsv.read(tsv_path(p))
    out = {}
    for r in rows:
        if r["country"] == country and (before is None or r["date"] < before):
            out[r["keyword"]] = r
    return out


# Output

def moved(now, was):
    """'39 (45)' when the rank changed since the last check, with the old one in brackets."""
    if not was or was == now:
        return now or "?"
    return f"{now or '?'} ({was})"


def table(p, rows, previous=None):
    previous = previous or {}
    head = ["keyword", "store", "api", "pop", "diff", "leader", "ahead of us"]
    lines = [head]
    for r in rows:
        was = previous.get(r["keyword"], {})
        lines.append([r["keyword"], moved(r["store_rank"], was.get("store_rank")),
                      moved(r["api_rank"], was.get("api_rank")), r["popularity"] or "-", r["difficulty"],
                      r["leader"][:28], r["ahead"]])
    widths = [max(len(str(line[i])) for line in lines) for i in range(len(head) - 1)]
    out = [f"{p.title}, {rows[0]['country'] if rows else ''} {rows[0]['date'] if rows else ''}"
           f"{'  (brackets: ' + next(iter(previous.values()))['date'] + ')' if previous else ''}"]
    for line in lines:
        out.append("  ".join(str(c).ljust(w) for c, w in zip(line, widths)) + "  " + line[-1])
    return "\n".join(out)


def report(p, country="us"):
    now = latest(p, country)
    if not now:
        raise SystemExit(f"no checks saved for {p.name} ({tsv_path(p)}); run `aso check`")
    day = max(r["date"] for r in now.values())
    rows = [r for r in now.values() if r["date"] == day]
    order = keywords(p, country)
    rows.sort(key=lambda r: order.index(r["keyword"]) if r["keyword"] in order else len(order))
    print(table(p, rows, latest(p, country, before=day)))


def best(r):
    """The store's rank where the app is in its top 12, the API's past that, or None."""
    for rank_ in (r.get("store_rank", ""), r.get("api_rank", "")):
        if rank_.isdigit():
            return int(rank_)
    return None


def summary(p):
    """One line per storefront (the US, then ASO_COUNTRIES): phrases in the top 10 and 50,
    ranked at all, unranked, and how many moved since the check before."""
    lines = [["country", "date", "phrases", "top10", "top50", "ranked", "unranked", "moved"]]
    for country in ["us"] + [c for c in p.get("ASO_COUNTRIES") or [] if c != "us"]:
        now = latest(p, country)
        if not now:
            lines.append([country, "no check yet"])
            continue
        day = max(r["date"] for r in now.values())
        ranks = [best(r) for r in now.values() if r["date"] == day]
        was = latest(p, country, before=day)
        up = down = 0
        for r in now.values():
            if r["date"] == day and r["keyword"] in was:
                a, b = best(r) or 999, best(was[r["keyword"]]) or 999
                up, down = up + (a < b), down + (a > b)
        moves = ", ".join(f"{word} {n}" for word, n in (("up", up), ("down", down)) if n) or "-"
        lines.append([country, day, len(ranks), sum(1 for r in ranks if r and r <= 10),
                      sum(1 for r in ranks if r and r <= 50), sum(1 for r in ranks if r),
                      sum(1 for r in ranks if not r), moves])
    widths = [max(len(str(line[i])) for line in lines if len(line) > 2) for i in range(len(lines[0]))]
    return f"{p.title} by storefront\n" + "\n".join(
        "  ".join(str(c).ljust(w) for c, w in zip(line, widths)).rstrip() for line in lines)


def top(p, term, country="us", depth=20):
    """Who holds a keyword: the store's top 12 and the API's top `depth`, with ratings."""
    app_id, _, competitors = config(p)
    tracked = {v: k for k, v in competitors.items()} | {app_id: p.title}
    api = api_search(term, country) or []
    store = store_search(term, country) or []
    info = {r["id"]: r for r in api}
    print(f"store search, {country}: {term}")
    for i, r in enumerate(store, 1):
        a = info.get(r["id"], {})
        mark = "  <-" if r["id"] in tracked else ""
        print(f"  {i:2}. {a.get('name') or r['name']}  ({a.get('ratings', '?')} ratings){mark}")
    print(f"search API, top {depth}:")
    for i, r in enumerate(api[:depth], 1):
        mark = "  <-" if r["id"] in tracked else ""
        print(f"  {i:2}. {r['name']}  ({r['ratings']} ratings, ${r['price']}){mark}")
    print(f"  {p.title}: store {rank(store, app_id, STORE_DEPTH)}, API {rank(api, app_id, API_LIMIT)}")


def suggest(p, seed, country="us", ranked=False):
    """Apple's suggestions for a seed and the seed plus each letter: keyword ideas."""
    app_id, keywords, _ = config(p)
    tracked = {k.lower() for k in keywords}
    cache, found = {}, []
    for prefix in [seed] + [f"{seed} {c}" for c in "abcdefghijklmnopqrstuvwxyz"]:
        for term in hints(prefix, country, cache):
            if term not in found:
                found.append(term)
    for term in found:
        note = "tracked" if term in tracked else ""
        if ranked:
            note = f"API {rank(api_search(term, country), app_id, API_LIMIT)}  {note}"
        print(f"  {term}  {note}".rstrip())


# Daily run

LABEL = "local.leadkit.aso"


def plist(hour, minute, home, python, log):
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "leadkit.aso_cli", "check", "--all"],
        "EnvironmentVariables": {"PYTHONPATH": str(home), "LEADKIT_DATA": str(product.DATA)},
        "WorkingDirectory": str(home),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
    })
