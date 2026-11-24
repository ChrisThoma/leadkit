"""aso export: each language's keyword field, ready to paste into App Store Connect.

The fields come from aso/locales.md. Nothing here talks to App Store Connect,
so a field only counts as pasted once `aso export --pasted <locale>` says so,
which saves the field with the date to aso/pasted.tsv. If `aso locales` later
writes a different field for that language, it reads "changed since pasted".
"""
from datetime import date

from . import aso_locales, aso_review, tsv

FIELDS = ["date", "locale", "field"]


def path(p):
    return p.dir / "aso" / "pasted.tsv"


def pasted(p):
    """The newest pasted row per locale."""
    _, rows = tsv.read(path(p))
    return {r["locale"]: r for r in rows}


def status(field, row):
    if not row:
        return "not pasted"
    if row["field"] != field:
        return f"changed since pasted {row['date']}"
    return f"pasted {row['date']}"


def states(p):
    """{locale: state} for every field in locales.md. The listing file's locale is pushed by the
    app's own sync script with its next version, so it's never pasted."""
    fields, done, live = aso_review.fields(p), pasted(p), aso_locales.listing(p)
    return {c: (f"from {live['path']}, pushed with the next version" if live and c == aso_locales.LISTING_LOCALE
                else status(f, done.get(c))) for c, f in fields.items()}


def is_open(state):
    return not state.startswith(("pasted", "from "))


def mark(p, locales, today=None):
    fields = aso_review.fields(p)
    codes = list(fields) if locales == ["all"] else locales
    missing = [c for c in codes if c not in fields]
    if missing:
        raise SystemExit(f"no field in locales.md for {', '.join(missing)}; have: {', '.join(fields)}")
    today = today or date.today().isoformat()
    rows = [{"date": today, "locale": c, "field": fields[c]} for c in codes]
    path(p).parent.mkdir(parents=True, exist_ok=True)
    tsv.append(path(p), rows, FIELDS)
    return rows


def render(p, only=None, todo=False):
    if not aso_locales.report_path(p).exists():
        raise SystemExit(f"no keyword fields for {p.name} yet; run `aso locales -p {p.name}` (about 35 minutes)")
    fields, state = aso_review.fields(p), states(p)
    out = []
    for code, field in fields.items():
        if only and code not in only:
            continue
        if todo and not is_open(state[code]):
            continue
        out.append(f"{code}  {aso_locales.LOCALES[code][0]}  ({state[code]})\n{field}\n")
    left = sum(map(is_open, state.values()))
    head = (f"{p.title}: {len(fields)} keyword fields from aso/locales.md, {left} not pasted or changed.\n"
            "Paste each into the Keywords box for that language in App Store Connect, then run\n"
            f"`aso export -p {p.name} --pasted <locale> ...` (or `--pasted all`).\n")
    return head + "\n" + "\n".join(out)
