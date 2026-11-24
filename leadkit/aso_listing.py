"""aso export --asc / --play: an app's listing files turned into what each store's tools read.

en-US comes from the app's listing file (ASO_LISTING_FILE), every other language from
<ASO_LISTING_DIR>/<locale>.json in the app's repo: name, subtitle, promotionalText,
description, whatsNew, and optionally play.title, play.shortDescription, play.fullDescription.
en-GB, en-AU and en-CA reuse the en-US copy unless they have a file of their own. Keyword
fields always come from aso/locales.md (en-US from the listing file), never from the json.

Nothing here talks to a store: --asc writes an `asc metadata` folder for
`asc metadata validate` and `asc metadata push --dry-run`, --play writes the fastlane
folders under ASO_PLAY_METADATA_DIR that the app's Play sync reads, and --play-notes
writes each language's whatsNew for a Play release (or its playWhatsNew, when the Android
release has different news from the iOS one).
"""
import ast, json, re

from . import aso_review

ENGLISH = ["en-US", "en-GB", "en-AU", "en-CA"]
LIMITS = {"name": 30, "subtitle": 30, "promotionalText": 170, "description": 4000, "keywords": 100}
PLAY_LIMITS = {"title": 30, "shortDescription": 80, "fullDescription": 4000}
PLAY_NOTES_LIMIT = 500
# App Store locale to Google Play's language code, where they differ.
PLAY_CODE = {
    "es-MX": "es-419", "it": "it-IT", "sv": "sv-SE", "no": "no-NO", "da": "da-DK", "fi": "fi-FI",
    "pl": "pl-PL", "cs": "cs-CZ", "hu": "hu-HU", "el": "el-GR", "tr": "tr-TR", "ru": "ru-RU",
    "he": "iw-IL", "hi": "hi-IN", "ja": "ja-JP", "ko": "ko-KR", "zh-Hans": "zh-CN", "zh-Hant": "zh-TW",
}
# The listing file's names for each field.
FILE_KEYS = {"NAME": "name", "SUBTITLE": "subtitle", "PROMO": "promotionalText", "DESCRIPTION": "description",
             "KEYWORDS": "keywords", "WHATS_NEW": "whatsNew", "PLAY_WHATS_NEW": "playWhatsNew", "SUPPORT_URL": "supportUrl",
             "MARKETING_URL": "marketingUrl", "PRIVACY_URL": "privacyPolicyUrl"}


def english(p):
    """en-US from the listing file, parsed rather than run (running it prints or writes files)."""
    path = p.repo_path(p.need("ASO_LISTING_FILE"))
    out = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in FILE_KEYS:
            out[FILE_KEYS[node.targets[0].id]] = ast.literal_eval(node.value)
    return out


def translations(p):
    folder = p.repo_path(p.need("ASO_LISTING_DIR"))
    return {f.stem: json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))}


def languages(p):
    """{locale: copy} for every language, English variants filled from en-US."""
    en, other = english(p), translations(p)
    out = {"en-US": en}
    for loc in ENGLISH[1:]:
        out[loc] = {**en, **other.pop(loc, {})}
    return {**out, **other}


def problems(loc, copy, brand):
    found = []
    for key, limit in LIMITS.items():
        value = copy.get(key) or ""
        if not value and key != "keywords":
            found.append(f"{loc}: {key} empty")
        elif len(value) > limit:
            found.append(f"{loc}: {key} is {len(value)}/{limit}")
    if not copy.get("name", "").startswith(brand):
        found.append(f"{loc}: name doesn't start with {brand}")
    if re.search(r"—|–| - ", copy.get("description", "") + copy.get("promotionalText", "")):
        found.append(f"{loc}: dash in copy")
    return found


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def build_asc(p, version, out):
    """Write the asc metadata folder; return the problems (the folder is written either way)."""
    langs, fields = languages(p), aso_review.fields(p)
    en = langs["en-US"]
    brand = en["name"].split(":")[0]
    urls = {k: en[k] for k in ("supportUrl", "marketingUrl") if en.get(k)}
    found = []
    for loc, copy in langs.items():
        copy = {**copy, "keywords": en["keywords"] if loc == "en-US" else fields.get(loc)}
        if not copy["keywords"]:
            found.append(f"{loc}: no keyword field in locales.md")
        # Whether Apple needs a What's New in every localization of an update is unchecked;
        # `asc metadata validate` says. Until then a missing one is listed.
        if not copy.get("whatsNew"):
            found.append(f"{loc}: no whatsNew")
        found += problems(loc, copy, brand)
        info = {"name": copy["name"], "subtitle": copy.get("subtitle", "")}
        if en.get("privacyPolicyUrl"):
            info["privacyPolicyUrl"] = en["privacyPolicyUrl"]
        ver = {k: copy[k] for k in ("description", "keywords", "promotionalText", "whatsNew") if copy.get(k)}
        write_json(out / "app-info" / f"{loc}.json", info)
        write_json(out / "version" / version / f"{loc}.json", {**ver, **urls})
    return found


def build_play(p):
    """Write each translated language's Play copy; return the problems. en-US isn't touched."""
    rel = p.get("ASO_PLAY_METADATA_DIR")
    if not rel:
        raise SystemExit(f"{p.name} has no ASO_PLAY_METADATA_DIR, so there's no Play listing to write")
    root, found = p.repo_path(rel), []
    for loc, copy in translations(p).items():
        play = copy.get("play")
        if not play:
            found.append(f"{loc}: no play copy")
            continue
        for key, limit in PLAY_LIMITS.items():
            if not play.get(key):
                found.append(f"{loc}: play.{key} empty")
            elif len(play[key]) > limit:
                found.append(f"{loc}: play.{key} is {len(play[key])}/{limit}")
        folder = root / PLAY_CODE.get(loc, loc)
        folder.mkdir(parents=True, exist_ok=True)
        for name, key in (("title.txt", "title"), ("short_description.txt", "shortDescription"),
                          ("full_description.txt", "fullDescription")):
            (folder / name).write_text(play.get(key, "") + "\n")
    return found


def build_play_notes(p, out):
    """Write each language's whatsNew as <Play code>.txt; return the problems. A bad line gets no file.

    When the English listing file has PLAY_WHATS_NEW, every language's line comes from
    playWhatsNew instead, and a language without one is a problem rather than a fallback to
    whatsNew, which can name an iOS feature the Android app doesn't have."""
    out.mkdir(parents=True, exist_ok=True)
    found = []
    langs = languages(p)
    key = "playWhatsNew" if langs["en-US"].get("playWhatsNew") else "whatsNew"
    for loc, copy in sorted(langs.items()):
        notes = (copy.get(key) or "").strip()
        if not notes:
            found.append(f"{loc}: {key} empty")
        elif len(notes) > PLAY_NOTES_LIMIT:
            found.append(f"{loc}: {key} is {len(notes)}/{PLAY_NOTES_LIMIT}")
        else:
            (out / f"{PLAY_CODE.get(loc, loc)}.txt").write_text(notes + "\n")
    return found
