---
name: leadkit
description: App Store keyword and listing work with leadkit's `aso` tools, plus leadkit setup and adding apps. Use when the user says /leadkit, "keywords", "how are the ranks", "update the keywords", "keyword fields for other languages", "translate the listing", "check the translations", "set up leadkit", or "add <app> to leadkit". A leads pass (Reddit/Threads replies) is the leads-pass skill, not this one.
---

# leadkit: keywords, listings, setup

The tools are `aso` and `leads` from the leadkit repo (README "How to use it" has
the whole picture). Inside an app's repo the product is picked from the repo;
elsewhere pass `-p <name>`, before or after the subcommand. `leads setup --check`
reports where every app is and what comes next; start there when the ask is vague.

## Where things live

Your data is in `$LEADKIT_DATA` (default `~/leadkit-data`), apart from the code.

- **English listing (name, subtitle, keywords):** the app's own listing file in
  its repo, named by `ASO_LISTING_FILE` in `products/<name>/config.py`. That file
  is the only source; never write English keywords anywhere else.
- **Tracked phrases:** `ASO_KEYWORDS` in the product's config. The daily launchd
  job ranks them into `aso/ranks.tsv`.
- **Other languages:** `products/<name>/aso/locales.md` (fields),
  `aso/seeds/<locale>.txt` (seed phrases to correct), `aso/review.md` (dictionary
  check), `aso/pasted.tsv` (what's been put in App Store Connect).
- **Analyses:** `products/<name>/aso/keywords-<date>.md`. Read the newest before
  proposing keyword changes.

## What the user might ask

**"How are the keywords doing?"** `aso report -p <app>`. The daily job already
checked; don't run `aso check` unless asked. Say which `store` ranks moved
(brackets are the check before) and stop. Ranks past 12 in the store and 200 in
the API are normal while an app has few ratings.

**"Find better keywords."** Read the newest `keywords-<date>.md`, then measure
candidates: `aso suggest <word>` (what Apple completes), `aso top "<phrase>"` (who
holds it, their ratings), `aso check --dry-run --only "<phrase>" ...` (about 8 s a
phrase). Choose high popularity, low difficulty, a word the name and subtitle
don't already index, and a feature the app really has. Write the result in a new
`keywords-<date>.md`, change `KEYWORDS` in the listing file (100 characters max),
add new phrases to `ASO_KEYWORDS`, then `aso locales --only en-US`. It ships with
the app's next version; nothing goes to the store from here.

**"Keyword fields for other languages."** Ask which languages, unless named. Then
`aso locales --only <locales>` (all 40 take about 35 minutes; say the estimate
first and run it in the background), then `aso locales --review` (about 10
minutes). In review.md, fix what's under "Look at these first" in
`aso/seeds/<locale>.txt` and rerun that locale. "Unverified" words need a speaker.

**Meaning review (before the user sees any translated field).** The dictionary
check can't tell a real word with the wrong meaning. Give a fresh agent the English
listing file, `ASO_ABOUT`, `ASO_AVOID` and the fields. It lists, per locale: words
whose meaning is wrong, features the app doesn't have, terms `ASO_AVOID` steers
away from, phrases a field claims but doesn't contain, and unnatural phrases. It
reports and doesn't edit. Fix what it finds, rerun those locales, and say which
findings need a native speaker.

**"Translate the listing."** Each language's name, subtitle, promo text,
description and `whatsNew` go in `<ASO_LISTING_DIR>/<locale>.json` in the app's
repo. Keyword fields never go there; the export reads them from `aso/locales.md`.

**"Put them on the store."** `aso export -p <app> --asc <version> --dir <dir>`
writes every language as an `asc metadata` folder and lists any problems;
`aso export -p <app> --play` writes the Play listings. Then
`asc metadata validate --dir <dir>` and `asc metadata push --dry-run`. Keep en-US in
the directory: a push deletes any localization the directory leaves out. Read the
dry run's deletes and stop if there are any. The real push only on the user's
explicit go-ahead naming the app and languages. Afterwards,
`aso export --pasted <locales>`.

**"Set up leadkit."** `leads setup` (asks before each change; `--check` only
reports; without a terminal it only reports unless `--yes`).

**"Add <app> to leadkit."** `leads setup --new <name>`, then fill in its
`config.py` and `cases.py`. Look at `examples/products/example/` in the repo for a
filled-in config.

## When done

If the data folder is a git repo, commit only the files this work touched there.
The listing file commits in the app's own repo.
