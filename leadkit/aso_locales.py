"""Keyword fields for every App Store localization.

For each language a product targets: start from seed phrases in that language,
widen them with Apple's own suggestions in the language's home storefront, score
each phrase there (popularity from how early Apple suggests something holding it, difficulty from
the top 10's ratings), and pack the best words into the 100-character field,
leaving out words the name and subtitle already carry.

Seeds for English locales are the product's ASO_KEYWORDS. Other languages are
drafted once by `claude -p` from ASO_ABOUT and saved to
products/<name>/aso/seeds/<locale>.txt, which is the file to correct when a
native speaker knows better; it's only regenerated with --refresh-seeds.

Which storefronts read which localization comes from Apple's table
(data/storefronts.tsv, from developer.apple.com's "App Store localizations",
2026-10-27). Apple calls the extra languages "supported"; it doesn't say their
keywords count in search, which is the common ASO claim (es-MX in the US, for
instance) and is untested here.
"""
import ast, csv, json, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import aso, tsv

# code: (Apple's name for the language, home storefront, what the seed prompt calls it)
LOCALES = {
    "en-US": ("English (US)", "us", "American English"),
    "en-GB": ("English (U.K.)", "gb", "British English"),
    "en-AU": ("English (Australia)", "au", "Australian English"),
    "en-CA": ("English (Canada)", "ca", "Canadian English"),
    "fr-FR": ("French", "fr", "French (France)"),
    "fr-CA": ("French (Canada)", "ca", "Canadian French"),
    "de-DE": ("German", "de", "German"),
    "es-ES": ("Spanish (Spain)", "es", "Spanish (Spain)"),
    "es-MX": ("Spanish (Mexico)", "mx", "Latin American Spanish (Mexico)"),
    "pt-BR": ("Portuguese (Brazil)", "br", "Brazilian Portuguese"),
    "pt-PT": ("Portuguese (Portugal)", "pt", "European Portuguese"),
    "it": ("Italian", "it", "Italian"),
    "nl-NL": ("Dutch", "nl", "Dutch"),
    "sv": ("Swedish", "se", "Swedish"),
    "no": ("Norwegian", "no", "Norwegian (Bokmål)"),
    "da": ("Danish", "dk", "Danish"),
    "fi": ("Finnish", "fi", "Finnish"),
    "pl": ("Polish", "pl", "Polish"),
    "cs": ("Czech", "cz", "Czech"),
    "sk": ("Slovak", "sk", "Slovak"),
    "hu": ("Hungarian", "hu", "Hungarian"),
    "ro": ("Romanian", "ro", "Romanian"),
    "el": ("Greek", "gr", "Greek"),
    "tr": ("Turkish", "tr", "Turkish"),
    "ru": ("Russian", "ru", "Russian"),
    "uk": ("Ukrainian", "ua", "Ukrainian"),
    "ja": ("Japanese", "jp", "Japanese"),
    "ko": ("Korean", "kr", "Korean"),
    "zh-Hans": ("Chinese (Simplified)", "cn", "Simplified Chinese (mainland China)"),
    "zh-Hant": ("Chinese (Traditional)", "tw", "Traditional Chinese (Taiwan)"),
    "th": ("Thai", "th", "Thai"),
    "vi": ("Vietnamese", "vn", "Vietnamese"),
    "id": ("Indonesian", "id", "Indonesian"),
    "ms": ("Malay", "my", "Malay"),
    "hi": ("Hindi", "in", "Hindi"),
    "ar": ("Arabic", "sa", "Arabic"),
    "he": ("Hebrew", "il", "Hebrew"),
    "hr": ("Croatian", "hr", "Croatian"),
    "sl": ("Slovenian", "si", "Slovenian"),
    "ca": ("Catalan", "es", "Catalan"),
}
# Written without spaces between words. The seeds put spaces in (ギター 指板 覚える),
# so those split; a suggestion has none and can't be split, so it only scores.
UNSPACED = {"ja", "zh-Hans", "zh-Hant", "th"}
FIELD_LIMIT = 100
# Phrases scored per locale: each costs a Search API call (3 s) and a few hints.
SCORED = 40
DIFFICULTY_FOR = 15
# Words that never earn their characters.
STOP = {"app", "apps", "the", "and", "for", "of", "with", "to", "de", "la", "le", "les", "des", "du", "el", "los",
        "las", "para", "con", "der", "die", "das", "und", "für", "mit", "di", "il", "per", "och", "og", "met",
        "voor", "het", "een", "na", "do", "da", "dos", "em", "pour", "et", "y", "e", "i", "en", "&", "vom", "von",
        "zum", "zur", "im", "am", "au", "aux", "del", "al", "della", "per", "op", "på", "af", "à", "a", "o", "no",
        "sur", "une", "un", "til", "sig", "pre", "pro", "для", "на", "в", "по", "za", "ve", "ile", "та", "і", "и",
        "dan",
        # "App" in other languages: every result is an app, so the word never earns its characters.
        "앱", "アプリ", "aplikasi", "application", "aplicación", "aplicativo", "applicazione",
        "aplicație", "aplicatie", "אפליקציה", "ऐप", "ứng", "dụng"}
FIELDS = ["date", "locale", "storefront", "phrase", "source", "popularity", "typed", "difficulty", "in_field"]
TABLE = Path(__file__).with_name("data") / "storefronts.tsv"


# Apple's storefront table

def storefronts():
    with TABLE.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def language(name):
    # Apple's table says both "Simplified Chinese" and "Chinese (Simplified)".
    return {"Simplified Chinese": "Chinese (Simplified)"}.get(name.strip(), name.strip())


def readers(locale, rows=None):
    """(countries where the locale is the default, countries where it's an extra language)."""
    name = LOCALES[locale][0]
    default, extra = [], []
    for r in rows or storefronts():
        if language(r["default"]) == name:
            default.append(r["country"])
        elif name in [language(x) for x in r["additional"].split(",") if x.strip()]:
            extra.append(r["country"])
    return default, extra


# Words

def unspaced(locale):
    return locale in UNSPACED


def units(phrase, locale):
    """What the keyword field has to hold for Apple to match a phrase."""
    phrase = phrase.lower().strip()
    if unspaced(locale):
        return [w for w in phrase.split() if w not in STOP]
    # Two Latin letters is filler or a fragment ("à", "rc"); in other scripts it can be a word (音).
    # A number is a word: a field holding "bit" without "8" doesn't cover "minuteur 2 levains".
    return [w for w in words(phrase) if w not in STOP and (len(w) > 2 or not latin(w) or w.isdigit())]


def words(phrase):
    return [w for w in re.split(r"[\s\-/,:|]+", phrase) if w]


def latin(word):
    return all(c < "\u0250" for c in word)


def known(unit, vocab):
    """A word the seeds use, allowing inflection and compounds (sauerteige, sauerteig-timer)."""
    # Two letters of ending covers sauerteig/sauerteige and timer/timers; more lets in
    # other apps' coinages (proof/proofbox).
    # The ending has to be letters: "timer44" is an app.
    return unit in vocab or any(len(v) > 4 and unit.startswith(v) and len(unit) - len(v) <= 2
                                and unit[len(v):].isalpha() for v in vocab)


def phrases_from_hint(hint, vocab, locale, avoid=()):
    """The parts of a suggestion made only of seed words. Suggestions are mostly
    app names ("doughly - sauerteig timer", "bread timer pro lite"), so
    a segment with any word the seeds don't use is somebody's brand or feature."""
    out = []
    for segment in re.split(r"\s+[-–|]\s+|[:,]\s*", hint.lower()):
        segment = segment.strip()
        u = units(segment, locale)
        ws = words(segment)
        # Nobody types a phrase that ends on filler: "bread maker al" is "AI bread maker" misread.
        if not u or ws[-1] in STOP or any(w in avoid for w in ws):
            continue
        # A lone word that only stems from a seed word is an app's name (breadly, doughzo).
        if len(ws) == 1 and ws[0] not in vocab:
            continue
        # Every word, not just the units: "leitura à primeira vista rc" is an app.
        if not unspaced(locale) and all(w in STOP or known(w, vocab) for w in ws):
            out.append(segment)
    return out


def suggested(locale):
    """How a phrase counts as suggested: some suggestion holds all its words,
    since in smaller stores they're nearly all app names, never the bare phrase."""
    def matches(term, found):
        need = units(term, locale)
        if unspaced(locale):
            return any(all(n in f.replace(" ", "") for n in need) for f in found)
        return any(all(any(w.startswith(n) for w in units(f, locale)) for n in need) for f in found)
    return matches


# The app's own listing file (ASO_LISTING_FILE, in its repo) holds the one localization the
# apps have. Its push script reads it, so that locale's field is read from it, never packed:
# otherwise one app can end up with three different English fields (the store, fields.py, locales.md).
LISTING_LOCALE = "en-US"


def listing(p):
    """NAME, SUBTITLE and KEYWORDS from the app's listing file, or None when it has none.

    Parsed rather than imported: the file prints its check table and writes METADATA.md when run.
    """
    rel = p.get("ASO_LISTING_FILE")
    if not rel:
        return None
    path = p.repo_path(rel)
    if not path.exists():
        raise SystemExit(f"{p.name}: ASO_LISTING_FILE {path} doesn't exist (it's local-only in the app repo)")
    found = {}
    for node in ast.parse(path.read_text()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("NAME", "SUBTITLE", "KEYWORDS")):
            found[node.targets[0].id.lower()] = ast.literal_eval(node.value)
    missing = {"name", "subtitle", "keywords"} - set(found)
    if missing:
        raise SystemExit(f"{p.name}: {path} has no {', '.join(sorted(m.upper() for m in missing))}")
    return found | {"path": rel}


def localized_listing(p, locale):
    """name and subtitle from <ASO_LISTING_DIR>/<locale>.json in the app's repo, or None.

    The translated listings live beside the English one, where the app's push reads them,
    so leadkit never holds a second copy of a localized name.
    """
    rel = p.get("ASO_LISTING_DIR")
    path = p.repo_path(rel) / f"{locale}.json" if rel else None
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["name"], data.get("subtitle", "")


def free_words(p, locale):
    """Words the name and subtitle already index for this locale."""
    if locale in p.get("ASO_LISTING", {}):
        name, subtitle = p.get("ASO_LISTING")[locale]
    elif localized_listing(p, locale):
        name, subtitle = localized_listing(p, locale)
    elif locale.startswith("en-"):
        live = listing(p)
        name, subtitle = ((live["name"], live["subtitle"]) if live
                          else (p.get("ASO_NAME", p.title), p.get("ASO_SUBTITLE", "")))
    else:
        name, subtitle = p.title, ""
    return set(units(f"{name} {subtitle}", locale))


def plural_pair(u, have):
    return u + "s" in have or (u.endswith("s") and u[:-1] in have)


def pack(scored, free, locale, limit=FIELD_LIMIT):
    """Greedy fill: each round takes the most valuable phrase that still fits,
    the cheaper one on a tie, and it pays only for words not already in the
    field, the name or the subtitle (a plural counts as its singular)."""
    chosen, field, used = [], [], 0
    left = list(scored)
    while left:
        best = None
        for s in left:
            have = set(free) | set(field)
            # Unspaced titles can't be split, so a word inside the name or subtitle text is free too.
            inside = unspaced(locale) and (lambda u: any(u in f for f in free)) or (lambda u: False)
            new = list(dict.fromkeys(u for u in units(s["phrase"], locale)
                                     if u not in have and not plural_pair(u, have) and not inside(u)))
            # A comma before each word, except the field's first.
            cost = max(sum(len(u) for u in new) + len(new) - (0 if field else 1), 0)
            if used + cost <= limit and (best is None or (s["value"], -cost) > (best[0]["value"], -best[2])):
                best = (s, new, cost)
        if best is None:
            break
        s, new, cost = best
        left.remove(s)
        field += new
        used += cost
        chosen.append(s["phrase"])
    return ",".join(field), chosen


def value(popularity, difficulty):
    # Difficulty discounts a phrase but never zeroes it: a popular, hard phrase
    # still beats one nobody types.
    return max(popularity, 1) * (1 - difficulty / 200)


# Seeds

def seeds_path(p, locale):
    return p.dir / "aso" / "seeds" / f"{locale}.txt"


def read_seeds(path):
    return [line.strip().lower() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def avoided(p):
    """{English word: why} the app's keywords stay away from (ASO_AVOID)."""
    return p.get("ASO_AVOID", {})


def avoid_words(p, locale):
    """ASO_AVOID's words plus the language's own (ASO_AVOID_BY_LOCALE), for Apple's suggestions:
    a local word for something the app lacks (kalendář), or another language's word that the
    storefront suggests (Spanish diario in the Catalan field, scored in the Spanish store)."""
    return set(avoided(p)) | set(p.get("ASO_AVOID_BY_LOCALE", {}).get(locale, ()))


def ground(p):
    """What the seeds should cover: the live English listing when there's a file, else the tracked phrases.
    Tracked phrases include ones kept only to watch, like words the field dropped."""
    live = listing(p)
    if not live:
        return ", ".join(p.need("ASO_KEYWORDS"))
    keywords = ", ".join(w.strip() for w in live["keywords"].split(",") if w.strip())
    return f'the name "{live["name"]}", the subtitle "{live["subtitle"]}" and the keywords {keywords}'


def prompt(p, locale):
    _, country, lang = LOCALES[locale]
    avoid = "".join(f"\n- {why}" for why in avoided(p).values())
    avoid = f" Don't target any of these, which bring searches for something else:{avoid}\n" if avoid else " "
    return f"""{p.need("ASO_ABOUT")}

List 15 to 20 short phrases that someone in that market would type into the App Store search, in {lang}, \
when looking for an app like this (storefront: {country.upper()}). Start with the one- and two-word terms people \
there type most for this kind of app, then longer phrases. Use the words people there really search with: \
native script and local terms, and English loanwords only where locals use them. Cover the same ground as the \
English listing: {ground(p)}.{avoid}Leave out app and brand names. \
Each phrase is a natural noun phrase a searcher types, correctly spelled with its diacritics: no verb standing \
for "maker", no words run together that the language writes apart, no plural ending split off with a hyphen. \
Keep numbers as digits ("2 step"). One phrase per line, lowercase, no numbering, nothing else."""


def clean_seeds(text):
    """claude -p's lines without list numbering or bullets. Only a number followed by "." or ")" is
    numbering: "2 stufen brot" keeps its 2 (a leading number was once stripped as a list number)."""
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])?\s*", "", line).strip().lower() for line in text.splitlines()]
    return [line for line in lines if line and len(line) < 60]


def seeds(p, locale, refresh=False, model="sonnet"):
    path = seeds_path(p, locale)
    if locale.startswith("en-") and not path.exists():
        avoid = avoided(p)
        return [k.lower() for k in p.need("ASO_KEYWORDS") if not any(w in avoid for w in words(k.lower()))]
    if path.exists() and not refresh:
        return read_seeds(path)
    print(f"  drafting {locale} seeds with claude -p", file=sys.stderr)
    out = subprocess.run(["claude", "-p", "--model", model], input=prompt(p, locale), capture_output=True,
                         text=True, timeout=300)
    lines = clean_seeds(out.stdout)
    if out.returncode or not lines:
        raise SystemExit(f"claude -p gave no seeds for {locale}: {out.stderr.strip()[:200]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {LOCALES[locale][2]} seed phrases for {p.title}, drafted by claude -p on {date.today()}.\n"
                    "# Correct or extend by hand; `aso locales --refresh-seeds` redrafts it.\n" + "\n".join(lines) + "\n")
    return lines


# One locale

def plan(p, locale, refresh=False, model="sonnet"):
    return finish(p, locale, score(p, locale, refresh, model))


def score(p, locale, refresh=False, model="sonnet"):
    """Popularity for the seeds and the suggestions they lead to (the suggestions host)."""
    _, country, _ = LOCALES[locale]
    seed = seeds(p, locale, refresh, model)
    vocab = {u for s in seed for u in units(s, locale)}
    cache, candidates = {}, {s: "seed" for s in seed}
    for s in seed:
        for hint in aso.hints(s, country, cache):
            for phrase in phrases_from_hint(hint, vocab, locale, avoid_words(p, locale)):
                candidates.setdefault(phrase, "suggested")
    scored = []
    for phrase, source in list(candidates.items())[:SCORED]:
        typed = aso.typed_letters(phrase, country, cache, suggested(locale))
        scored.append({"phrase": phrase, "source": source, "typed": typed, "popularity": aso.popularity(typed),
                       "difficulty": None})
    return scored


def finish(p, locale, scored):
    """Difficulty (the Search API host) and the packed field."""
    _, country, _ = LOCALES[locale]
    # Difficulty only for the phrases that could make the field; the rest pack on popularity.
    for s in sorted(scored, key=lambda s: -s["popularity"])[:DIFFICULTY_FOR]:
        s["difficulty"] = aso.difficulty(aso.api_search(s["phrase"], country, limit=10))[0]
    for s in scored:
        s["value"] = value(s["popularity"], s["difficulty"] or 0)
    field, chosen, source = choose(p, locale, scored)
    return {"locale": locale, "storefront": country, "field": field, "chosen": chosen, "scored": scored,
            "free": sorted(free_words(p, locale)), "source": source}


def choose(p, locale, scored):
    """(field, phrases it covers, listing file or None): the listing's field where there is one, else packed."""
    free = free_words(p, locale)
    live = listing(p) if locale == LISTING_LOCALE else None
    if not live:
        return (*pack(scored, free, locale), None)
    words = [w.strip().lower() for w in live["keywords"].split(",") if w.strip()]
    have = free | set(words)
    chosen = [s["phrase"] for s in scored
              if all(u in have or plural_pair(u, have) for u in units(s["phrase"], locale))]
    return ",".join(words), chosen, live["path"]


# Output

def section(result, rows=None):
    locale = result["locale"]
    default, extra = readers(locale, rows)
    lines = [f"## {locale}: {LOCALES[locale][0]}", ""]
    if default:
        lines.append(f"Default language in {len(default)} storefront{'s' * (len(default) != 1)}"
                     f"{': ' + ', '.join(default) if len(default) <= 12 else ''}.")
    if extra:
        lines.append(f"Extra language in {len(extra)}: {', '.join(extra)}.")
    origin = (f"from `{result['source']}` in the app's repo, the listing's only source (edit it there), "
              if result.get("source") else "")
    lines += ["", f"Keyword field ({len(result['field'])}/{FIELD_LIMIT}), {origin}scored in the "
              f"{result['storefront'].upper()} store:", "", "```", result["field"], "```", ""]
    if result["free"]:
        lines += [f"Already indexed from the name and subtitle: {', '.join(result['free'])}.", ""]
    lines += ["| phrase | from | popularity | difficulty | covered |", "| --- | --- | --- | --- | --- |"]
    for s in sorted(result["scored"], key=lambda s: -s["value"]):
        lines.append(f"| {s['phrase']} | {s['source']} | {s['popularity']} | "
                     f"{'' if s['difficulty'] is None else s['difficulty']} | "
                     f"{'yes' if s['phrase'] in result['chosen'] else ''} |")
    return "\n".join(lines) + "\n"


def locale_for(country):
    """The localization a storefront is scored for here: the first in LOCALES (ca is en-CA, es is es-ES)."""
    return next((code for code, (_, front, _) in LOCALES.items() if front == country), None)


def targeted(p, locale, limit=None):
    """The phrases the latest run packed into a language's field, the most valuable first.
    A locale run twice in a day appends the same rows twice, so each phrase counts once."""
    _, rows = tsv.read(p.dir / "aso" / "locale-keywords.tsv")
    rows = [r for r in rows if r["locale"] == locale]
    last = max((r["date"] for r in rows), default=None)
    found = {}
    for r in rows:
        if r["date"] == last and r["in_field"] == "yes":
            found.setdefault(r["phrase"], value(int(r["popularity"] or 0), int(r["difficulty"] or 0)))
    return sorted(found, key=found.get, reverse=True)[:limit]


def report_path(p):
    return p.dir / "aso" / "locales.md"


def write_report(p, results):
    head = (f"# {p.title}: keyword fields by App Store language\n\n"
            f"Generated by `aso locales` on {date.today()}. Popularity is how early Apple's search suggestions "
            "offer a phrase in that storefront (100 after two letters, 0 if never); difficulty comes from the "
            "rating counts of the top 10 apps for it. Both are estimates, not Apple figures. Non-English seed "
            "phrases were drafted by `claude -p` (aso/seeds/), so have a speaker check a field before it ships.\n\n")
    path = report_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    # Keep sections for locales this run didn't touch.
    kept = {m.group(1): m.group(0) for m in re.finditer(r"^## (\S+):.*?(?=^## |\Z)", old, re.S | re.M)}
    rows = storefronts()
    for r in results:
        kept[r["locale"]] = section(r, rows)
    order = [code for code in LOCALES if code in kept]
    path.write_text(head + "\n".join(kept[c].rstrip() + "\n" for c in order))
    return path


def save(p, results):
    path = p.dir / "aso" / "locale-keywords.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    tsv.append(path, [{"date": today, "locale": r["locale"], "storefront": r["storefront"], "phrase": s["phrase"],
                       "source": s["source"], "popularity": s["popularity"], "typed": s["typed"] or "",
                       "difficulty": "" if s["difficulty"] is None else s["difficulty"],
                       "in_field": "yes" if s["phrase"] in r["chosen"] else ""}
                      for r in results for s in r["scored"]], FIELDS)


def run(p, only=None, refresh=False, model="sonnet"):
    codes = only or p.get("ASO_LOCALES") or list(LOCALES)
    unknown = [c for c in codes if c not in LOCALES]
    if unknown:
        raise SystemExit(f"unknown locale {', '.join(unknown)}; have: {', '.join(LOCALES)}")
    # Drafting is claude -p, a minute or so apiece and outside Apple's limits, so it goes first, six at once.
    drafts = [c for c in codes if not c.startswith("en-") and (refresh or not seeds_path(p, c).exists())]
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(lambda c: seeds(p, c, refresh, model), drafts))

    def done(code, scored):
        result = finish(p, code, scored)
        print(f"{code:8} {result['field']}", flush=True)
        # Saved as it goes, so a long run that dies keeps what it finished.
        save(p, [result])
        write_report(p, [result])
        return result

    # Suggestions and the Search API are separate hosts with separate rate limits, so one
    # language's difficulty lookups run while the next one's suggestions are fetched. One
    # worker keeps the API at its pace and the report writes in order.
    with ThreadPoolExecutor(1) as api:
        pending = []
        for code in codes:
            print(f"{code}", file=sys.stderr)
            pending.append(api.submit(done, code, score(p, code)))
        results = [f.result() for f in pending]
    print(f"report: {report_path(p)}")
    return results
