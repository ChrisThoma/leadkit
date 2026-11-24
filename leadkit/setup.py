"""leads setup: get leadkit working on this Mac, or add a product, one step at a time.

    leads setup                      # check everything, asking before each change
    leads setup --check              # only report what's missing
    leads setup --yes                # make every change without asking
    leads setup --new dice           # add a product: products/dice/ with config.py and cases.py
    bin/setup                        # the same, before `leads` is linked

What it sets up on the Mac: your data folder (~/leadkit-data, or $LEADKIT_DATA)
with settings.py, the `leads`, `aso`, `asc-sales` and `play-sales` commands in
~/.local/bin, and the daily launchd job that runs `aso check --all`. For each product it checks the
config, the repo and the leads folder, and says which aso step comes next. It
never starts a long run (a rank check, keyword fields for 40 languages); those
are printed as next steps with how long they take.

Without a terminal (an agent running it) it only reports, unless --yes.
"""
import argparse, os, plistlib, shutil, subprocess, sys
from collections import namedtuple
from datetime import date
from pathlib import Path

from . import aso, aso_cli, aso_export, aso_locales, aso_review, product, threads, x
from .product import settings

BIN = Path.home() / ".local" / "bin"
COMMANDS = ["leads", "aso", "asc-sales", "play-sales"]
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{aso.LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "leadkit-aso.log"
# A rank check spaces Search API calls 3 s apart, plus suggestions: 23 keywords took about 3 minutes.
SECONDS_PER_KEYWORD = 8

# level is ok, todo (something's missing), next (a command to run) or note (fine as it is, worth knowing).
Step = namedtuple("Step", "level text fix", defaults=(None,))


# The Mac

def link_state(src, dest):
    if not (dest.is_symlink() or dest.exists()):
        return "missing"
    return "ok" if dest.resolve() == src.resolve() else "other"


def make_link(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(src)


def daily_state(plist, home, python):
    """("missing", None), ("ok", "HH:MM") or ("stale", why) for the daily check's launchd job."""
    if not plist.exists():
        return "missing", None
    job = plistlib.loads(plist.read_bytes())
    when = job.get("StartCalendarInterval", {})
    if job.get("EnvironmentVariables", {}).get("PYTHONPATH") != str(home):
        return "stale", f"runs another checkout ({job.get('EnvironmentVariables', {}).get('PYTHONPATH')})"
    if not Path(job["ProgramArguments"][0]).exists():
        return "stale", f"its Python is gone ({job['ProgramArguments'][0]})"
    return "ok", f"{when.get('Hour', 0):02}:{when.get('Minute', 0):02}"


def daily_time(plist, default="09:15"):
    try:
        when = plistlib.loads(plist.read_bytes()).get("StartCalendarInterval", {})
        return f"{when['Hour']:02}:{when['Minute']:02}"
    except (OSError, KeyError, ValueError):
        return default


def loaded(label=aso.LABEL):
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                          capture_output=True).returncode == 0


def machine_steps():
    steps = []
    v = sys.version_info
    steps.append(Step("ok" if v >= (3, 9) else "todo",
                      f"Python {v.major}.{v.minor} ({sys.executable})" + ("" if v >= (3, 9) else ", needs 3.9 or newer")))

    for name in COMMANDS:
        src, dest = product.HOME / "bin" / name, BIN / name
        state = link_state(src, dest)
        if state == "ok":
            steps.append(Step("ok", f"`{name}` command: {dest}"))
        elif state == "missing":
            steps.append(Step("todo", f"`{name}` isn't linked: {dest} -> {src}", lambda s=src, d=dest: make_link(s, d)))
        else:
            steps.append(Step("todo", f"{dest} points at {os.path.realpath(dest)}, not this checkout. Move it "
                                      "aside and run setup again."))
    if str(BIN) not in os.environ.get("PATH", "").split(":"):
        steps.append(Step("todo", f"{BIN} isn't on PATH. Add `export PATH=\"$HOME/.local/bin:$PATH\"` to ~/.zshrc."))

    steps += data_steps()

    state, info = daily_state(PLIST, product.HOME, Path(sys.executable))
    install = lambda at=daily_time(PLIST): aso_cli.daily(at, False)  # noqa: E731
    if state == "ok" and loaded():
        steps.append(Step("ok", f"daily keyword check (launchd) at {info}, log: {LOG}"))
    elif state == "ok":
        steps.append(Step("todo", "the daily keyword check is installed but not loaded", install))
    elif state == "missing":
        steps.append(Step("todo", "the daily keyword check isn't installed (`aso check --all` every day at "
                                  "09:15; change it with `aso daily --at HH:MM`)", install))
    else:
        steps.append(Step("todo", f"the daily keyword check {info}", install))

    state, info = daily_state(threads.INSIGHTS_PLIST, product.HOME, Path(sys.executable))
    install = lambda: threads.install_insights_job(daily_time(threads.INSIGHTS_PLIST, "09:20"), False)  # noqa: E731
    if state == "ok" and loaded(threads.INSIGHTS_LABEL):
        steps.append(Step("ok", f"daily Threads insights (launchd) at {info}, log: {threads.INSIGHTS_LOG}"))
    elif state == "missing":
        steps.append(Step("todo", "the daily Threads insights log isn't installed (`leads threads-insights` "
                                  "every day at 09:20; change it with `leads threads-insights --daily --at HH:MM`)",
                          install))
    elif state == "ok":
        steps.append(Step("todo", "the daily Threads insights log is installed but not loaded", install))
    else:
        steps.append(Step("todo", f"the daily Threads insights log {info}", install))

    state, info = daily_state(x.INSIGHTS_PLIST, product.HOME, Path(sys.executable))
    if state == "ok" and loaded(x.INSIGHTS_LABEL):
        steps.append(Step("ok", f"daily X insights (launchd) at {info}, log: {x.INSIGHTS_LOG}"))
    elif not (x.TOKEN_FILE.exists() or os.environ.get("X_BEARER_TOKEN")):
        steps.append(Step("note", f"no X API token ({x.TOKEN_FILE}), so no daily X insights. It needs an app "
                                  "with pay-per-use credits at console.x.com; then `leads x-insights --daily`"))
    else:
        install_x = lambda: x.install_insights_job(daily_time(x.INSIGHTS_PLIST, "09:25"), False)  # noqa: E731
        steps.append(Step("todo", "the daily X insights log isn't running (`leads x-insights --daily`)", install_x))

    if shutil.which("claude"):
        steps.append(Step("ok", "`claude` CLI, which drafts the seeds for `aso locales`"))
    else:
        steps.append(Step("note", "`claude` isn't on PATH; `aso locales` needs it to draft seeds in other languages"))

    # The leads pass starts with these; their keys are yours to add, so setup only looks.
    for tool, env, config in [("asc-sales", "ASC_KEY_ID", Path.home() / ".config/asc-sales/config.json"),
                              ("play-sales", "PLAY_BUCKET", Path.home() / ".config/play-sales/config.json")]:
        if not shutil.which(tool):
            steps.append(Step("note", f"`{tool}` isn't on PATH (link it from bin/ above)"))
        elif not (os.environ.get(env) or config.exists()):
            steps.append(Step("note", f"`{tool}` has no settings ({config} or ${env}); a leads pass notes "
                                      "that and goes on"))
        else:
            steps.append(Step("ok", f"`{tool}` and its settings"))
    return steps


def make_data():
    product.PRODUCTS.mkdir(parents=True, exist_ok=True)
    if not product.SETTINGS.exists():
        shutil.copy(product.SETTINGS_EXAMPLE, product.SETTINGS)


def data_steps():
    """The data folder: settings.py and products/, kept apart from the code."""
    if not product.SETTINGS.exists():
        return [Step("todo", f"no data folder settings at {product.SETTINGS}: copy settings.example.py there "
                             "and make products/", make_data)]
    steps = [Step("ok", f"data folder: {product.DATA}")]
    if "your_reddit_name" in product.SETTINGS.read_text():
        steps.append(Step("todo", f"fill in your accounts in {product.SETTINGS}"))
    if not (product.DATA / ".git").exists():
        steps.append(Step("note", f"{product.DATA} isn't a git repo. `git init` it (and keep it private: it "
                                  "names the people you reply to) to get a daily commit of ranks and leads"))
    return steps


# Products

def minutes(seconds):
    return f"about {max(1, round(seconds / 60))} minute{'s' if seconds >= 90 else ''}"


def product_steps(p):
    steps = []

    def say(level, text, fix=None):
        steps.append(Step(level, f"{p.name}: {text}", fix))

    if not p.get("REPO"):
        say("todo", "set REPO in config.py (the app's own repo)")
    elif not p.repo.is_dir():
        say("todo", f"REPO {p.get('REPO')} doesn't exist on this Mac")
    if p.leads.is_dir():
        say("ok", f"leads folder {p.leads}")
    else:
        say("todo", f"no leads folder at {p.leads}", lambda: p.leads.mkdir(parents=True))
    if not (p.dir / "cases.py").exists():
        say("todo", "no cases.py; tests/test_products.py checks every product's")

    missing = [k for k in ("SUBREDDITS", "SCORE_TABLES", "MIN_SCORE") if p.get(k) in (None, [], {})]
    if missing:
        say("todo", f"`leads reddit` has nothing to do until config.py sets {', '.join(missing)}")
    else:
        say("ok", f"Reddit: {len(p.get('SUBREDDITS'))} subs")
    if not p.get("THREADS_SEARCHES"):
        say("note", "no THREADS_SEARCHES, so `leads threads-searches` has nothing to open")
    if p.get("THREADS_KEYWORDS") and not threads.token_file(p).exists():
        say("note", f"`leads threads-api` is off until Meta approves keyword search and a token is in "
                    f"{threads.token_file(p)}")

    keywords = p.get("ASO_KEYWORDS")
    if not p.get("APP_STORE_ID"):
        say("note", "aso is off: set APP_STORE_ID and ASO_KEYWORDS in config.py to track App Store keywords")
        return steps
    if not keywords:
        say("todo", f"aso is off until ASO_KEYWORDS lists some (`aso suggest <word> -p {p.name}` finds candidates)")
        return steps
    if aso.tsv_path(p).exists():
        last = max((r["date"] for r in aso.latest(p).values()), default="never")
        say("ok", f"keyword ranks for {len(keywords)} keywords, last checked {last}")
    else:
        say("next", f"first rank check: `aso check -p {p.name}` ({minutes(len(keywords) * SECONDS_PER_KEYWORD)}); "
                    "the daily job does it after that")
    if not aso_locales.report_path(p).exists():
        if not p.get("ASO_ABOUT"):
            say("todo", "set ASO_ABOUT in config.py, which `aso locales` uses to draft other languages' seeds")
        say("next", f"keyword fields for every language: `aso locales -p {p.name}` (about 35 minutes)")
    elif not (p.dir / "aso" / "review.md").exists():
        say("next", f"dictionary check of those fields: `aso locales --review -p {p.name}` (about 10 minutes)")
    else:
        try:
            state = aso_export.states(p)
        except SystemExit as e:  # the app's listing file is local-only, so another Mac may lack it
            say("todo", str(e).removeprefix(f"{p.name}: "))
            return steps
        left = [c for c, st in state.items() if aso_export.is_open(st)]
        if left:
            say("next", f"{len(left)} of {len(state)} keyword fields aren't recorded as pasted into App Store "
                        f"Connect: `aso export -p {p.name} --todo`")
        else:
            say("ok", f"all {len(state)} keyword fields recorded as pasted")
    return steps


CONFIG = '''"""{title}: what its leads look like. Started by `leads setup --new` on {day};
fill in each block, then add example posts to cases.py.
"""

NAME = {title!r}
REPO = {repo!r}
LEADS_DIR = "leads"
# Drafts older than this are cleared as skip.
STALE_DAYS = 4

# Reddit
USER_AGENT = "{name}-watch/0.1 (by u/{account})"
PAUSE = 35.0
# Answer subs: people ask questions here, a reply answers first.
SUBREDDITS = []
# Ad subs: you post an ad of your own here (`leads posts`). Keys in leadkit/posts.py:
# {{"sub": {{"flair": "...", "every_days": 30, "not_before": "YYYY-MM-DD", "rules": "..."}}}}
POST_SUBS = {{}}
# Subs small enough to read every new post of, as well as searching them.
NEW_FEEDS = SUBREDDITS
# Each runs once over all SUBREDDITS as one multireddit.
SEARCHES = []
# Weighted regexes scored against title and body; a lead has to reach MIN_SCORE.
SIGNALS = {{}}
# Sales, launch posts, gear: anywhere a reply would read as an ad.
NEGATIVE = {{}}
MIN_SCORE = 5
SCORE_TABLES = [(None, SIGNALS), (None, NEGATIVE)]

# Threads, searched in Chrome (`leads threads-searches`):
# {{"group": [(query, TOP or RECENT, is_community, tag_id), ...]}}
TOP, RECENT = "", "&filter=recent"
THREADS_SEARCHES = {{
    "keywords": [({search!r}, RECENT, False)],
}}

# App Store keywords (`aso`). aso takes part once APP_STORE_ID and ASO_KEYWORDS are set.
{aso}
'''

ASO_ON = '''APP_STORE_ID = {app_store_id}
ASO_KEYWORDS = []
# The live name and subtitle; English locales don't spend keyword characters on their words.
ASO_NAME = ""
ASO_SUBTITLE = ""
# What `aso locales` tells claude -p when it drafts seed phrases in other languages.
ASO_ABOUT = ""
# Name to App Store ID, for the "ahead of us" column.
ASO_COMPETITORS = {{}}'''

CASES = '''"""{title}'s lead and not-lead examples, checked against its score tables.

Add the titles of threads worth answering to LEADS, and near misses that
aren't to NOT_LEADS, as they turn up.
"""

LEADS = []
NOT_LEADS = []
'''


def scaffold(name, title, repo, app_store_id):
    folder = product.PRODUCTS / name
    if folder.exists():
        raise SystemExit(f"products/{name} already exists")
    aso_block = (ASO_ON.format(app_store_id=app_store_id) if app_store_id
                 else "# APP_STORE_ID = 0\n# ASO_KEYWORDS = []")
    (folder / "leads").mkdir(parents=True)
    (folder / "config.py").write_text(CONFIG.format(title=title, name=name, repo=repo, day=date.today(),
                                                     search=title.lower(),
                                                     account=settings.REDDIT_REPLY_ACCOUNT, aso=aso_block))
    (folder / "cases.py").write_text(CASES.format(title=title))
    return folder


# Walking through

def asker(mode):
    def ask(question):
        if mode == "yes":
            return True
        if mode == "check":
            return False
        answer = input(f"     {question} [Y/n] ").strip().lower()
        return answer in ("", "y", "yes")
    return ask


def walk(steps, ask):
    """Print each step, offer its fix, and return what's still open."""
    marks = {"ok": "ok  ", "todo": "todo", "next": "next", "note": "note"}
    left = []
    for s in steps:
        print(f"{marks[s.level]} {s.text}")
        if s.fix and ask("Do it now?"):
            s.fix()
            print("     done")
        elif s.level in ("todo", "next"):
            left.append(s)
    return left


def new_product(args, ask_text):
    name = args.new
    title = args.title or ask_text("App name", name.replace("-", " ").title())
    repo = args.repo or ask_text("Its repo", f"~/Development/{name}")
    app_id = args.app_store_id or ask_text("App Store ID (blank if it isn't on the store yet)", "")
    folder = scaffold(name, title, repo, int(app_id) if app_id else None)
    print(f"made {folder}/config.py, cases.py and leads/")
    return product.Product(name)


def main(argv=None):
    try:
        run(argv)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nstopped; nothing after this step was changed")


def run(argv=None):
    ap = argparse.ArgumentParser(prog="leads setup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report, change nothing")
    ap.add_argument("--yes", action="store_true", help="make every change without asking")
    ap.add_argument("--new", metavar="NAME", help="add a product (a short lowercase name, like proofer)")
    ap.add_argument("--title", help="with --new: the app's display name")
    ap.add_argument("--repo", help="with --new: the app's repo, like ~/Development/dice-app")
    ap.add_argument("--app-store-id", help="with --new: its App Store ID, if it has one")
    args = ap.parse_args(argv)

    interactive = sys.stdin.isatty() and not args.check and not args.yes
    mode = "yes" if args.yes else "ask" if interactive else "check"
    if mode == "check" and not args.check:
        print("(no terminal, so only reporting; pass --yes to make the changes)\n")

    def ask_text(question, default):
        if not interactive:
            return default
        return input(f"{question} [{default}]: ").strip() or default

    ask = asker(mode)
    print("This Mac")
    left = walk(machine_steps(), ask)
    products = [new_product(args, ask_text)] if args.new else product.everything()
    for p in products:
        print(f"\n{p.title}")
        left += walk(product_steps(p), ask)

    print()
    if left:
        print("Still to do:")
        for s in left:
            print(f"  - {s.text}")
    else:
        print("Everything's set up.")
    print("\nHow the pieces fit together: \"How to use it\" in the README.")


if __name__ == "__main__":
    main()
