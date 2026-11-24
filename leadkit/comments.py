"""Reddit comments that use a product's phrases, as leads (`leads comments`).

The post watcher only sees posts. Most of the threads worth a reply that
F5Bot used to find were ones whose title never said the app's subject: someone
answering used the phrase. F5Bot emails those within about two hours, but
its free plan stops at 20 alerts a day, which a common phrase reaches.
Arctic Shift won't search comment text across Reddit, and a phrase search
inside a busy sub can time out, so a run lists
each sub's recent comments and matches the phrases locally, as the post
watcher does with posts.

`--scheduled` is what the hourly launchd job runs: find new threads, hand
them to a headless Claude session that reads each one and drafts a reply or
skips it, then show a Mac banner only for the drafts, so you hear about
threads worth answering, not every hit.
"""
import html, os, plistlib, re, shlex, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

from . import arctic, kinds, reddit, tsv
from . import product
from .product import settings

FIELDS = "id,body,author,link_id,subreddit,created_utc"
MAX_PAGES = 10
LABEL = "local.leadkit.comments"
LOG = Path.home() / "Library" / "Logs" / "leadkit-comments.log"
MODEL = "claude-opus-5-5"
SKILL = product.HOME / "plugin" / "skills" / "leads-pass" / "SKILL.md"


def plist_path(name):
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.{name}.plist"


def listing(sub, since, get=arctic.get):
    """Every comment in r/<sub> since the epoch second `since`, newest first."""
    out, seen, before = [], set(), None
    for _ in range(MAX_PAGES):
        params = {"subreddit": sub, "after": int(since), "limit": 100, "sort": "desc", "fields": FIELDS}
        if before:
            params["before"] = before
        try:
            page = get("comments/search", params) or []
        except arctic.Error as err:
            # A sub can answer its first page and time out on the next;
            # keep what came back rather than lose the sub.
            if not out:
                raise
            print(f"  r/{sub}: stopped after {len(out)} comments ({err})", file=sys.stderr)
            break
        fresh = [c for c in page if c["id"] not in seen]
        seen.update(c["id"] for c in fresh)
        out += [c for c in fresh if int(c["created_utc"]) >= since]
        if not fresh or len(page) < 100:
            break
        oldest = min(int(c["created_utc"]) for c in page)
        if oldest <= since:
            break
        before = oldest + 1
    return out


def find(p, hours=3, max_post_days=5, get=arctic.get, now=None):
    """New threads (not in the leads file) where a comment from the last `hours`
    used one of the product's COMMENT_PHRASES. The archive takes up to an hour
    to pick up a comment, so an hourly job looks back three."""
    now = now or datetime.now(timezone.utc).timestamp()
    phrases = p.need("COMMENT_PHRASES")
    subs = [s for s in (p.get("COMMENT_SUBS") or p.need("SUBREDDITS")) if reddit.allowed(p, s)]
    own = settings.REDDIT_OWN_ACCOUNTS
    seen = reddit.load_seen(p)
    hits = {}  # post id -> (phrase, comment)
    for sub in subs:
        try:
            found = listing(sub, now - hours * 3600, get=get)
        except arctic.Error as err:
            print(f"  r/{sub}: {err}", file=sys.stderr)
            continue
        for c in found:
            pid = (c.get("link_id") or "").removeprefix("t3_").lower()
            if not pid or pid in seen or pid in hits or (c.get("author") or "").lower() in own:
                continue
            body = html.unescape(c.get("body") or "")
            phrase = next((q for q in phrases if arctic.matches(q, body)), None)
            if phrase:
                hits[pid] = (phrase, c | {"body": body})
    if not hits:
        return []
    posts = {}
    ids = sorted(hits)
    for k in range(0, len(ids), 100):
        for x in get("posts/ids", {"ids": ",".join(ids[k:k + 100]), "fields": arctic.POST_FIELDS}) or []:
            posts[x["id"].lower()] = x
    today = datetime.fromtimestamp(now).date().isoformat()
    rows = []
    for pid, (phrase, c) in hits.items():
        x = posts.get(pid)
        if not x or (x.get("author") or "").lower() in own:
            continue
        if now - int(x["created_utc"]) > max_post_days * 86400:
            continue
        e = arctic.entry(x)
        link = f"https://www.reddit.com/r/{c['subreddit']}/comments/{pid}/comment/{c['id']}/"
        snippet = " ".join(c["body"].split())[:240]
        rows.append({"found": today, "posted": e["posted"], "subreddit": e["sub"], "author": e["author"],
                     "title": e["title"], "url": e["url"], "status": "new", "kind": kinds.DOMAIN,
                     "notes": f"From comment search ({phrase.strip()}): u/{c.get('author')} {link} \"{snippet}\""})
    return rows


def run(p, dry_run=False, **kw):
    """Find and append. Returns the rows added."""
    rows = find(p, **kw)
    for r in rows:
        print(f"r/{r['subreddit']}  {r['title']}\n      {r['url']}\n      {r['notes'][:160]}")
    print(f"{len(rows)} new thread(s) from comments", file=sys.stderr)
    if dry_run or not rows:
        return rows
    seen = reddit.load_seen(p)  # a session may have logged one meanwhile
    rows = [r for r in rows if reddit.post_id(r["url"]) not in seen]
    if rows:
        tsv.ensure(p.reddit_tsv, ["kind"])
        tsv.append(p.reddit_tsv, rows, reddit.FIELDS)
    return rows


def prompt(p, rows):
    lines = "\n".join(f"- {r['url']}  ({r['title']}) {r['notes'][:200]}" for r in rows)
    return f"""Scheduled comment-watcher triage for {p.title}. Nobody is watching this session.

The hourly watcher just added these Reddit threads to {p.title}'s reddit-leads.tsv as `new`. Each
was found the way a leads pass finds them: its post scored as a lead ("Watcher [n]"), scored as a near
miss ("Near miss [n]"; read it in full, a pass drafts from these about as often), or a comment in it used
one of the phrases F5Bot used to watch ("From comment search"):

{lines}

For each thread:
1. Read it with `leads -p {p.name} thread <url>`. Its header's "N comments archived" counts the comments
   Arctic Shift holds; it doesn't mean the thread is locked.
2. Decide whether it's worth a reply, by the leads-pass skill ({SKILL}, steps 3, 5 and 6) and any notes
   on replies in this app's repo. Skip threads off the app's topic, threads already answered well, and
   threads we already replied in.
3. Skip: `leads -p {p.name} set <url> status=skip notes+="<short reason>"`.
   Draft: check every feature the reply names against the app's code, then
   `printf '%s' "$reply" | leads -p {p.name} set <url> status=draft reply=-`.
   Write it in the voice the leads-pass skill describes.

Don't post anything, open a browser or the drafts page, commit, or edit any file. Finish with one line
per thread: DRAFT or SKIP, the URL, and why."""


def claude(text, repo):
    """Run the triage headless in the app's repo, so its CLAUDE.md and memory load."""
    tools = ["Bash(leads:*)", "Bash(printf:*)", "Read", "Grep", "Glob"]
    subprocess.run(["claude", "-p", text, "--model", MODEL, "--allowedTools", *tools,
                    "--add-dir", str(product.HOME / "plugin")],
                   cwd=repo, timeout=30 * 60, check=False)


def drafts_command(p):
    """The shell line a banner click runs: the drafts page, in the background,
    with this Python (the click's shell has a bare PATH)."""
    home = Path(__file__).resolve().parents[1]
    q = shlex.quote
    return (f"cd {q(str(p.repo))} && PYTHONPATH={q(str(home))} LEADKIT_DATA={q(str(product.DATA))} nohup {q(sys.executable)} -m leadkit.cli "
            f"-p {q(p.name)} drafts >> {q(str(LOG))} 2>&1 &")


def notify(title, text, command=None):
    """A Mac banner. With terminal-notifier (brew, since 2026-11-20) a click runs
    `command`, which opens the drafts page. A plain
    osascript banner only opens Script Editor when clicked, so it's the fallback."""
    tn = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    if Path(tn).exists():
        args = [tn, "-title", title, "-message", text, "-sound", "Glass", "-group", LABEL]
        if command:
            args += ["-execute", command]
        r = subprocess.run(args, check=False, capture_output=True, text=True)
        # Until you allow it in System Settings > Notifications it prints
        # "Notifications are not allowed for this application" and shows nothing.
        if r.returncode == 0 and "not allowed" not in (r.stdout + r.stderr):
            return
        print(f"  terminal-notifier: {(r.stdout + r.stderr).strip()}; plain banner instead", file=sys.stderr)
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}" sound name "Glass"'],
                   check=False)


def commit(p, day):
    from . import aso_cli
    aso_cli.commit_ranks(product.DATA, [p.reddit_tsv], day,
                         message=f"{p.title}: comment watcher {day}")


def new_posts(p):
    """What a pass's `leads reddit` finds, near misses included, over the last
    day; anything older is already in the file from an earlier run."""
    try:
        return reddit.watch(p, days=1, near_misses=True)
    except Exception as err:  # a failed listing mustn't cost the comment leads
        print(f"  post search failed: {err}", file=sys.stderr)
        return []


def scheduled(p, claude=claude, notify=notify, commit=commit, posts=new_posts, **kw):
    """The hourly job: find, triage headless, banner the drafts, commit the file.
    It finds what a leads pass's Reddit step does: the post search with its near misses, and
    comments using the product's phrases. Threads and X need Chrome, so they stay
    in the pass."""
    print(f"--- {datetime.now().isoformat(timespec='minutes')}", file=sys.stderr)
    rows = run(p, **kw)
    rows += [r for r in posts(p) if reddit.post_id(r["url"]) not in {reddit.post_id(x["url"]) for x in rows}]
    if not rows:
        return
    claude(prompt(p, rows), p.repo)
    urls = {reddit.post_id(r["url"]) for r in rows}
    drafted = [r for r in tsv.read(p.reddit_tsv)[1]
               if reddit.post_id(r.get("url")) in urls and tsv.status(r) == "draft"]
    if drafted:
        first = drafted[0]
        more = f" (+{len(drafted) - 1} more)" if len(drafted) > 1 else ""
        notify(f"{p.title}: reply drafted", f"r/{first['subreddit']}: {first['title']}{more}. Click to open the drafts page.", drafts_command(p))
    commit(p, datetime.now().date().isoformat())


def job_plist(name, home, python, log):
    path = f"{home}/bin:{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    return plistlib.dumps({
        "Label": f"{LABEL}.{name}",
        "ProgramArguments": [python, "-m", "leadkit.cli", "-p", name, "comments", "--scheduled"],
        "EnvironmentVariables": {"PYTHONPATH": str(home), "LEADKIT_DATA": str(product.DATA), "PATH": path},
        "WorkingDirectory": str(home),
        "StartInterval": 3600,
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
    })


def install_job(p, off):
    domain = f"gui/{os.getuid()}"
    target = plist_path(p.name)
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True)
    if off:
        target.unlink(missing_ok=True)
        return print(f"removed {target}")
    p.need("COMMENT_PHRASES")
    target.write_bytes(job_plist(p.name, Path(__file__).resolve().parents[1], sys.executable, LOG))
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    print(f"hourly comment watcher for {p.title}: {target}\nlog: {LOG}")
