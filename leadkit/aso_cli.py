"""aso: App Store keyword ranks, popularity and difficulty for every product.

Run inside an app repo and the product is picked from it; pass -p/--product
anywhere else. A product takes part once its config.py has APP_STORE_ID and
ASO_KEYWORDS (ASO_COMPETITORS is optional). `check --all` ranks every product in the
US and the storefronts in settings.py's ASO_COUNTRIES, each with its own language's
phrases, skipping those whose language a product doesn't have on the store.

    aso check                        # rank every keyword, save to aso/ranks.tsv, show what moved
    aso check --all                  # every product with keywords, then commit the ranks (over an hour)
    aso check --all -c fr de         # every product, only those storefronts (a few minutes each)
    aso check -c de                  # this product in one storefront, with the phrases aso locales chose there
    aso check --only "sourdough timer" --no-hints
    aso report [-c de]               # the last saved check, no network, plus one line per storefront
    aso top "sourdough timer"        # who holds a keyword, with rating counts
    aso suggest sourdough [--ranked] # Apple's suggestions to mine for new keywords
    aso daily [--at 09:15]           # optional: a daily launchd `check --all`; --off removes it
    aso locales [--only de-DE ja]    # a keyword field for every App Store language, into aso/locales.md
    aso locales --review             # look every field word up on Wiktionary, into aso/review.md
    aso export [--todo] [--only ja]  # each language's field to paste into App Store Connect
    aso export --pasted de-DE fr-FR  # record those fields as pasted (or --pasted all)
    aso export --asc 1.5 [--dir D]   # every language's listing as an `asc metadata` folder
    aso export --play-notes --dir D  # each language's whatsNew as <Play code>.txt for a Play release
    aso export --play                # every translated Play listing into the app's fastlane folders

New here? See "How to use it" in the README, or run `leads setup`.
"""
import argparse, datetime, os, subprocess, sys, tempfile
from pathlib import Path

from . import aso, aso_export, aso_listing, aso_locales, aso_review, product, asc_state


def daily(at, off):
    target = Path.home() / "Library" / "LaunchAgents" / f"{aso.LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True)
    if off:
        target.unlink(missing_ok=True)
        return print(f"removed {target}")
    hour, minute = (int(x) for x in at.split(":"))
    log = Path.home() / "Library" / "Logs" / "leadkit-aso.log"
    target.write_bytes(aso.plist(hour, minute, product.HOME, sys.executable, log))
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    print(f"daily check at {at}: {target}\nlog: {log}")


def commit_ranks(repo, paths, day, message=None):
    """Commit these paths in `repo` when it's a git repo of its own (`git init` your
    data folder to keep a history of ranks and leads); otherwise do nothing.
    Only these paths, so other staged or unstaged work stays out of it. No push."""
    top = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top or Path(top).resolve() != Path(repo).resolve():
        return
    rel = [str(Path(x).relative_to(repo)) for x in paths if Path(x).exists()]
    if not rel or not subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", *rel],
                                     capture_output=True, text=True).stdout.strip():
        return
    subprocess.run(["git", "-C", str(repo), "add", "--", *rel], check=True)  # a new file isn't tracked yet
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message or f"aso: ranks {day}", "--", *rel], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aso", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--product", help="product name (default: the app repo you're in)")
    # -p works after the subcommand too (`aso export -p proofer`); SUPPRESS keeps one given before it.
    either = argparse.ArgumentParser(add_help=False)
    either.add_argument("-p", "--product", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ap.add_argument("-c", "--country", default="us", help=f"storefront ({', '.join(aso.STOREFRONTS)})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser
    sub.add_parser = lambda *a, **k: add(*a, parents=[either], **k)

    c = sub.add_parser("check", help="rank every keyword and save the result")
    c.add_argument("-c", "--country", nargs="+", dest="countries", metavar="CC", help="only these storefronts")
    c.add_argument("--all", action="store_true", help="every product with ASO_KEYWORDS")
    c.add_argument("--only", nargs="+", help="these keywords instead of the product's list")
    c.add_argument("--no-hints", action="store_true", help="skip the popularity lookups (faster)")
    c.add_argument("--dry-run", action="store_true", help="print, don't save")

    r = sub.add_parser("report", help="the last saved check")
    r.add_argument("-c", "--country", default=argparse.SUPPRESS, help="storefront")

    t = sub.add_parser("top", help="who holds a keyword")
    t.add_argument("keyword")
    t.add_argument("--depth", type=int, default=20)

    s = sub.add_parser("suggest", help="Apple's search suggestions for a seed")
    s.add_argument("seed")
    s.add_argument("--ranked", action="store_true", help="also rank the app for each (slow: 3 s each)")

    lo = sub.add_parser("locales", help="a keyword field for every App Store language")
    lo.add_argument("--only", nargs="+", metavar="LOCALE", help=f"these locales ({', '.join(aso_locales.LOCALES)})")
    lo.add_argument("--refresh-seeds", action="store_true", help="redraft the non-English seeds with claude -p")
    lo.add_argument("--model", default="sonnet", help="model for claude -p (default: sonnet)")
    lo.add_argument("--review", action="store_true", help="check the saved fields against Wiktionary instead")

    x = sub.add_parser("export", help="the keyword fields to paste into App Store Connect")
    x.add_argument("--only", nargs="+", metavar="LOCALE", help="these locales")
    x.add_argument("--todo", action="store_true", help="only fields not pasted yet, or changed since")
    x.add_argument("--pasted", nargs="+", metavar="LOCALE", help="record these as pasted ('all' for every one)")
    x.add_argument("--asc", metavar="VERSION", help="write the listing as an asc metadata folder for this version")
    x.add_argument("--dir", help="where --asc or --play-notes writes (default: a temp folder, printed)")
    x.add_argument("--play", action="store_true", help="write the translated Play listings")
    x.add_argument("--play-notes", action="store_true", help="write each language's whatsNew for a Play release")

    d = sub.add_parser("daily", help="install or remove the daily check")
    d.add_argument("--at", default="09:15", help="local time, HH:MM")
    d.add_argument("--off", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "daily":
        return daily(args.at, args.off)
    if args.cmd == "check" and args.all:
        # -c names storefronts; without it, the US and every storefront the app has a language for.
        asked = args.countries or ([args.country] if args.country != "us" else None)
        checked = [p for p in product.everything() if p.get("ASO_KEYWORDS")]
        runs = [(p, (["us"] if asked is None or "us" in asked else []) + aso.countries(p, asked)) for p in checked]
        total = sum(len(aso.keywords(p, c)) for p, stores in runs for c in stores)
        print(f"{total} phrases, {total * 4 // 60 + 1} to {total * 7 // 60 + 1} minutes", file=sys.stderr)
        for p, stores in runs:
            skipped = [c for c in asked or [] if c not in stores]
            if skipped:
                print(f"{p.title}: not ranked in {', '.join(skipped)}, its language isn't recorded as on the store")
            for country in stores:
                aso.check(p, country, with_hints=not args.no_hints, save=not args.dry_run)
            if len(stores) > 1 and not args.dry_run:
                print(aso.summary(p))
        if not args.dry_run:
            commit_ranks(product.DATA, [aso.tsv_path(p) for p in checked], datetime.date.today().isoformat())
        return

    p = product.pick(args.product)
    if args.cmd == "check":
        for country in args.countries or [args.country]:
            aso.check(p, country, only=args.only, with_hints=not args.no_hints, save=not args.dry_run)
    elif args.cmd == "report":
        aso.report(p, args.country)
        if aso.countries(p):
            print("\n" + aso.summary(p))
    elif args.cmd == "top":
        aso.top(p, args.keyword, args.country, args.depth)
    elif args.cmd == "suggest":
        aso.suggest(p, args.seed, args.country, args.ranked)
    elif args.cmd == "export":
        if args.asc or args.play or args.play_notes:
            found = []
            if args.asc:
                out = Path(args.dir or tempfile.mkdtemp(prefix=f"asc-{p.name}-"))
                found += aso_listing.build_asc(p, args.asc, out)
                if p.get("APP_STORE_ID"):
                    stop = asc_state.version_problem(p.get("APP_STORE_ID"), args.asc)
                    if stop:
                        found.append("STOP: " + stop)
                print(f"asc metadata for {args.asc}: {out}\n"
                      f"next: asc metadata validate --dir {out} --output table")
            if args.play:
                found += aso_listing.build_play(p)
                print(f"Play listings: {p.repo_path(p.get('ASO_PLAY_METADATA_DIR'))}")
            if args.play_notes:
                out = Path(args.dir or tempfile.mkdtemp(prefix=f"play-notes-{p.name}-"))
                found += aso_listing.build_play_notes(p, out)
                print(f"Play release notes: {out}")
            for line in found:
                print("  " + line)
            return 1 if found else 0
        if args.pasted:
            rows = aso_export.mark(p, args.pasted)
            print(f"recorded {len(rows)} as pasted: {aso_export.path(p)}")
        else:
            print(aso_export.render(p, args.only, args.todo), end="")
    elif args.cmd == "locales":
        if args.review:
            aso_review.run(p, args.only)
        else:
            aso_locales.run(p, args.only, args.refresh_seeds, args.model)


if __name__ == "__main__":
    sys.exit(main())
