"""A dictionary check on the keyword fields `aso locales` wrote.

Every word in every field is looked up on English Wiktionary, which is free,
needs no key and isn't the model that drafted the seeds, and is shown beside
its English meanings. Two kinds of word get flagged for a speaker to look at:
ones Wiktionary has no entry for (made up, a compound, or a scrap of an app's
name) and ones none of whose meanings touch the app's subject (the product's
ASO_TOPIC) or learning ("appi", father-in-law, in Finnish). It can't say whether
people really search a word; that's what the popularity column in locales.md is for.

Writes products/<name>/aso/review.md.
"""
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date

from . import aso_locales

API = "https://en.wiktionary.org/api/rest_v1/page/definition/"
AGENT = "leadkit-aso-review/1.0"
# Wiktionary's codes where the App Store's differ. Norwegian often lands under "other".
# Croatian is filed under Serbo-Croatian.
CODES = {"no": ["nb", "no", "nn", "other"], "zh-Hans": ["zh"], "zh-Hant": ["zh"], "hr": ["sh", "hr"]}
PAUSE = 0.5  # four lookups at once drew 429s within a minute
FAILED = object()
# "plural of nota", "inflection of drewniany: ...": the meaning is on the lemma.
FORM_OF = re.compile(r"\bof ([^\s:;,(“”\"]+)")
# Stems every app's field may touch: learning, practice and the like. A product adds its own
# subject's English stems in ASO_TOPIC (["knit", "yarn", "stitch"]); a word none of whose
# meanings match either is flagged "off topic?".
GENERAL = ["learn", "study", "train", "teach", "lesson", "quiz", "practi", "exercis", "beginner",
           "skill", "knowledge", "remember", "memor", "daily"]


def topic(words=()):
    return re.compile("|".join(re.escape(w) for w in [*words, *GENERAL]), re.I)


TOPIC = topic()


def fields(p):
    """{locale: field} from locales.md, in report order."""
    text = aso_locales.report_path(p).read_text()
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"^## (\S+):.*?^```\n(.*?)\n```", text, re.S | re.M)}


def codes(locale):
    return CODES.get(locale, [locale.split("-")[0]])


def strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def meanings(entry, locale):
    """English definitions for the locale's language from a Wiktionary REST reply."""
    if not isinstance(entry, dict):
        return []
    for code in codes(locale):
        found = [strip(d["definition"]) for usage in entry.get(code, [])
                 for d in usage.get("definitions", []) if isinstance(d, dict) and strip(d.get("definition", ""))]
        if found:
            return found
    return []


def fetch(title):
    """The reply for one page title, None if there's no page, FAILED if Wiktionary didn't answer."""
    req = urllib.request.Request(API + urllib.parse.quote(title), headers={"User-Agent": AGENT})
    for wait in (10, 30, 60, None):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429 or wait is None:
                print(f"  {e.code} for {title}", file=sys.stderr)
                return FAILED
            print(f"  429, waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
        except Exception as e:  # a blip loses one word, shown as "lookup failed", not the run
            print(f"  {e} for {title}", file=sys.stderr)
            return FAILED
    return FAILED


def lookup(word):
    """The reply for a word, trying it capitalized too (German nouns)."""
    result = None
    for title in dict.fromkeys([word, word[:1].upper() + word[1:]]):
        result = fetch(title)
        if result is not None:
            return result
    return result


def on_topic(found, subject=TOPIC):
    return any(subject.search(m) for m in found)


def verdict(word, found, locale="", english=False, failed=False, subject=TOPIC, keep=()):
    # ASO_REVIEW_KEEP: words a speaker has cleared that Wiktionary misreads (a brand, a coinage).
    if word.isascii() and word in keep:
        return ""
    if failed:
        return "lookup failed"
    if not found:
        if english:
            return "English word"
        # Chinese, Japanese and Thai fields hold whole compounds Wiktionary rarely has.
        return "" if aso_locales.unspaced(locale) else "no entry"
    return "" if on_topic(found, subject) else "off topic?"


def check(locale, field, look=lookup, subject=TOPIC, keep=()):
    rows = []
    for word in [w for w in field.split(",") if w]:
        reply = look(word)
        found = [] if reply is FAILED else meanings(reply, locale)
        # Wiktionary files some languages under "other" (Slovenian words, among others), mixed
        # with every other unsorted language, so it can clear a word but never flag one.
        if not found and reply is not FAILED and on_topic(meanings(reply, "other"), subject):
            found = meanings(reply, "other")
        if found and not on_topic(found, subject):
            lemmas = list(dict.fromkeys(m.group(1) for m in map(FORM_OF.search, found) if m))
            for lemma in lemmas[:1]:
                base = look(lemma)
                if base is not FAILED:
                    found += [f"{lemma}: {m}" for m in meanings(base, locale)[:2]]
        if found:  # on-topic meanings first, so the table shows why a word passed
            found.sort(key=lambda m: not subject.search(m))
        english = reply is not FAILED and not found and bool(meanings(reply, "en"))
        rows.append({"word": word, "meanings": found[:3],
                     "flag": verdict(word, found, locale, english, reply is FAILED, subject, keep)})
    return rows


# Flags that usually mean a wrong word. "no entry" and "lookup failed" only mean Wiktionary couldn't
# say: inflected forms and compounds land there while being right, so they go below.
LIKELY = {"off topic?", "English word"}


def write(p, checked):
    lines = [f"# {p.title}: keyword field review", "",
             f"Generated by `aso locales --review` on {date.today()} from locales.md. Each word's English "
             "meanings come from en.wiktionary.org. A clean row only says the word is real, not that people "
             "search it.", "",
             "To fix a word, edit `aso/seeds/<locale>.txt` and run `aso locales --only <locale>` again.", "",
             "## Look at these first", "",
             "None of the word's meanings mention the app's subject or learning (\"off topic?\"), or it's an English word "
             "in another language's field. These are usually real mistakes.", ""]

    def listed(keep):
        out = []
        for locale, rows in checked.items():
            flagged = [f"{r['word']} ({r['flag']}{': ' + r['meanings'][0] if r['meanings'] else ''})"
                       for r in rows if r["flag"] and keep(r["flag"])]
            if flagged:
                out.append(f"- **{locale}**: " + "; ".join(flagged))
        return out or ["Nothing."]

    lines += listed(lambda flag: flag in LIKELY)
    lines += ["", "## Unverified", "",
              "Wiktionary has no entry for the word in that language (\"no entry\") or didn't answer. Inflected "
              "forms and compounds land here even when they're right, so these need a speaker, not a fix.", ""]
    lines += listed(lambda flag: flag not in LIKELY)
    for locale, rows in checked.items():
        lines += ["", f"## {locale}: {aso_locales.LOCALES[locale][0]}", "", "| word | meanings | flag |",
                  "| --- | --- | --- |"]
        for r in rows:
            text = " / ".join(m.replace("|", "\\|")[:80] for m in r["meanings"])
            lines.append(f"| {r['word']} | {text} | {r['flag']} |")
    path = p.dir / "aso" / "review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def run(p, only=None, look=None):
    found = fields(p)
    codes_ = only or list(found)
    missing = [c for c in codes_ if c not in found]
    if missing:
        raise SystemExit(f"no field in locales.md for {', '.join(missing)}; run aso locales first")
    checked, subject, keep = {}, topic(p.get("ASO_TOPIC") or ()), set(p.get("ASO_REVIEW_KEEP") or ())
    for code in codes_:
        print(code, file=sys.stderr)
        checked[code] = check(code, found[code], look or lookup, subject, keep)
    path = write(p, checked)
    flags = sum(1 for rows in checked.values() for r in rows if r["flag"])
    print(f"{flags} words flagged in {len(checked)} languages: {path}")
    return checked
