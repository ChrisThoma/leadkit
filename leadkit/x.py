"""X: cross-posting a Threads post, the leads searches a pass
runs in Chrome, marking posted replies, and the daily insights log.

Posting and searching happen in Chrome (Claude in Chrome), signed in as
your X account (X_ACCOUNT in settings). The X API is pay-per-use since 2026-02 with no free tier, so
the only API call here is the daily read of our own posts' metrics (about
$0.001 a post), with an app bearer token from console.x.com.

A new X account starts with "graduated access": X says its posts are shown to
fewer people until it trusts the account.
On X a link counts as 23 characters whatever its length, and the limit is 280.
"""
import json, os, plistlib, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import kinds, threads, tsv
from . import product
from .product import settings

BASE = "https://x.com"
LIMIT = 280
LINK_WEIGHT = 23
TOP, LATEST = "", "&f=live"
URL = re.compile(r"https?://\S+")


# Length and campaign codes

def length(text):
    """X's count: every link is 23 characters."""
    return len(URL.sub("x" * LINK_WEIGHT, text))


def campaign(text):
    """Threads campaign codes become X ones, so a sale traces back to the right channel:
    ct=threads_idea -> ct=x_idea, utm_source=threads -> utm_source=x."""
    text = re.sub(r"\bct=threads(?=[_&\s]|$)", "ct=x", text)
    return re.sub(r"utm_source(%3D|=)threads\b", r"utm_source\1x", text)


# Cross-posting

LINK_IN_REPLY = re.compile(r"\s*Link in the reply\.?\s*$")


def _sentences(para):
    return re.findall(r"[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$", para)


def _pieces(para):
    """A paragraph, or its sentences packed into pieces that fit when it doesn't."""
    if length(para) <= LIMIT:
        return [para]
    out, cur = [], ""
    for s in (s.strip() for s in _sentences(para)):
        if cur and length(f"{cur} {s}") > LIMIT:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    return out + ([cur] if cur else [])


def crosspost(post, reply=""):
    """A Threads post and its link reply as X posts, each within 280: the post
    split at paragraphs (or sentences), and the reply joined onto the last part
    when it fits, dropping "Link in the reply." there. Campaign codes become X's."""
    post, reply = campaign(post.strip()), campaign((reply or "").strip())
    if length(post) <= LIMIT:
        return [post] + ([reply] if reply else [])
    parts = []
    for para in (p.strip() for p in post.split("\n\n") if p.strip()):
        for piece in _pieces(para):
            if parts and length(f"{parts[-1]}\n\n{piece}") <= LIMIT:
                parts[-1] = f"{parts[-1]}\n\n{piece}"
            else:
                parts.append(piece)
    if reply:
        last = LINK_IN_REPLY.sub("", parts[-1])
        joined = f"{last} {reply}"
        if length(joined) <= LIMIT:
            parts[-1] = joined
        else:
            parts += _pieces(reply)
    return parts


def threads_post(tok, url=None):
    """Our latest Threads post (or the one at url) and the link reply under it."""
    from . import threadsapi
    posts = [p for p in threadsapi.call("me/threads", tok, {
        "limit": 25, "fields": "id,text,permalink,media_type,media_url,is_reply"}).get("data", [])
        if p.get("text") and not p.get("is_reply")]
    if url:
        key = threads.path_of(url.replace("threads.net", "threads.com"))
        posts = [p for p in posts if threads.path_of(p.get("permalink", "")) == key]
    if not posts:
        raise SystemExit(f"no Threads post {'at ' + url if url else 'found'}")
    post = posts[0]
    own = [r for r in threadsapi.call(f"{post['id']}/conversation", tok, {"fields": "text,username"}).get("data", [])
           if (r.get("username") or "").lower() == settings.THREADS_ACCOUNT]
    return post, (own[0]["text"] if own else "")


def download_media(post, folder):
    """The post's video or image, for the X composer's file input."""
    if not post.get("media_url") or post.get("media_type") not in ("VIDEO", "IMAGE"):
        return None
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{post['id']}.{'mp4' if post['media_type'] == 'VIDEO' else 'jpg'}"
    if not out.exists():
        urllib.request.urlretrieve(post["media_url"], out)
    return out


def print_crosspost(tok, url=None, folder=None):
    post, reply = threads_post(tok, url)
    parts = crosspost(post["text"], reply)
    print(f"# from {post['permalink']}")
    media = download_media(post, folder) if folder else None
    if media:
        print(f"# media for the first post: {media}")
    for i, part in enumerate(parts, 1):
        print(f"\n# {i}/{len(parts)} ({length(part)} of {LIMIT})\n{part}")


# Leads searches (Chrome)

def search_url(query, tab=TOP, *_):
    return f"{BASE}/search?q={quote(query)}&src=typed_query{tab}"


def groups(p):
    """X_SEARCHES when the product has them, else its Threads searches (and the
    shared app-kind ones), with Threads' Recent tab as X's Latest."""
    if p.get("X_SEARCHES"):
        return dict(p.get("X_SEARCHES"))
    return {g: [(s[0], LATEST if len(s) > 1 and s[1] == threads.RECENT else TOP) for s in group]
            for g, group in threads.groups(p).items()}


def searches(p, groups_wanted=()):
    table = groups(p)
    for g in [g for g in groups_wanted if g in table] or list(table):
        label = ("app: posts under a day old" if threads.kind_of(p, g) == kinds.APP_KIND else "domain")
        print(f"# {g} ({label})")
        for s in table[g]:
            print(search_url(*s))


# Run in the search results tab after scrolling. One line per post: date,
# status URL, @author, likes/replies from the action bar, first 160 characters.
EXTRACT_JS = r"""(()=>{const seen=new Set(),out=[];
document.querySelectorAll('article').forEach(a=>{
const t=a.querySelector('time');if(!t)return;const l=t.closest('a');const h=l&&l.getAttribute('href');
if(!h||seen.has(h))return;seen.add(h);
const txt=(a.querySelector('[data-testid=tweetText]')||{}).innerText||'';
const bar=(a.querySelector('[role=group][aria-label]')||{getAttribute:()=>''}).getAttribute('aria-label');
out.push(t.getAttribute('datetime').slice(5,16).replace('T',' ')+' https://x.com'+h+' @'+h.split('/')[1]
+' | '+bar+' | '+txt.replace(/\s+/g,' ').slice(0,160));});
return out.join('\n');})()"""


def status_path(url):
    """/<user>/status/<id> whatever the host or query."""
    m = re.search(r"/([^/?#]+)/status/(\d+)", url)
    return f"/{m.group(1).lower()}/status/{m.group(2)}" if m else url


def mark_posted(p, items):
    """Mark X rows posted. Each item is "thread-url [our-reply-url]", or a thread URL alone."""
    replies = {}
    for item in items:
        parts = item.split()
        if parts:
            replies[status_path(parts[0])] = parts[1] if len(parts) > 1 else ""

    def update(r):
        path = status_path(r.get("url") or "")
        if path in replies and tsv.status(r) in tsv.OPEN | {"skip"}:
            r["status"] = "posted"
            if replies[path]:
                r["notes"] = f"Reply: {replies[path]} {r.get('notes') or ''}".strip()
            return True
        return False
    changed = tsv.rewrite(p.x_tsv, update)
    for r in changed:
        print(f"posted: {p.title}: @{r.get('author') or ''} {r['url']}", file=sys.stderr)
    return changed


# Daily insights (X API, pay-per-use)

API = "https://api.x.com/2"
TOKEN_FILE = Path(os.path.expanduser("~/.config/leadkit/x_bearer_token"))
METRICS = {"views": "impression_count", "likes": "like_count", "replies": "reply_count",
           "reposts": "retweet_count", "quotes": "quote_count", "bookmarks": "bookmark_count"}
INSIGHTS_FIELDS = ["date", "posted", "url", "text"] + list(METRICS)
INSIGHTS_TSV = product.DATA / "x-insights.tsv"
INSIGHTS_LABEL = "local.leadkit.x-insights"
INSIGHTS_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{INSIGHTS_LABEL}.plist"
INSIGHTS_LOG = Path.home() / "Library" / "Logs" / "leadkit-x-insights.log"


def token():
    t = os.environ.get("X_BEARER_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")
    if not t:
        sys.exit(f"no X token: create an app at console.x.com (pay-per-use credits), copy its Bearer Token "
                 f"into {TOKEN_FILE} (chmod 600) or set X_BEARER_TOKEN")
    return t


def call(path, tok, params=None):
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"X API {e.code} on {path}: {e.read().decode(errors='replace')[:300]}")


def log_insights(tok, path, limit=25):
    """One row per recent post (not replies) per day, like threads-insights.tsv."""
    me = call(f"users/by/username/{settings.X_ACCOUNT}", tok)["data"]["id"]
    posts = call(f"users/{me}/tweets", tok, {"max_results": max(5, min(limit, 100)),
                                              "exclude": "replies,retweets",
                                              "tweet.fields": "created_at,public_metrics"}).get("data", [])
    today = datetime.now(timezone.utc).date().isoformat()
    out = []
    for post in posts:
        m = post.get("public_metrics", {})
        out.append({"date": today, "posted": post.get("created_at", "")[:16].replace("T", " "),
                    "url": f"{BASE}/{settings.X_ACCOUNT}/status/{post['id']}",
                    "text": post.get("text", "").replace("\t", " ").replace("\n", " ")[:80],
                    **{k: m.get(v, "") for k, v in METRICS.items()}})
    kept = [r for r in tsv.read(path)[1] if r["date"] != today]
    tsv.write(path, INSIGHTS_FIELDS, kept + out)
    return out


def insights_plist(hour, minute, home, python, log):
    return plistlib.dumps({
        "Label": INSIGHTS_LABEL,
        "ProgramArguments": [python, "-m", "leadkit.cli", "x-insights", "--scheduled"],
        "EnvironmentVariables": {"PYTHONPATH": str(home), "LEADKIT_DATA": str(product.DATA)},
        "WorkingDirectory": str(home),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
    })


def install_insights_job(at, off):
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(INSIGHTS_PLIST)], capture_output=True)
    if off:
        INSIGHTS_PLIST.unlink(missing_ok=True)
        return print(f"removed {INSIGHTS_PLIST}")
    token()  # no point scheduling a job that can only fail
    hour, minute = (int(v) for v in at.split(":"))
    INSIGHTS_PLIST.write_bytes(insights_plist(hour, minute, Path(__file__).resolve().parents[1],
                                              sys.executable, INSIGHTS_LOG))
    subprocess.run(["launchctl", "bootstrap", domain, str(INSIGHTS_PLIST)], check=True)
    print(f"daily X insights at {at}: {INSIGHTS_PLIST}\nlog: {INSIGHTS_LOG}")


def scheduled_insights(day=None):
    from . import aso_cli
    log_insights(token(), INSIGHTS_TSV)
    day = day or datetime.now().date().isoformat()
    aso_cli.commit_ranks(INSIGHTS_TSV.parent, [INSIGHTS_TSV], day, message=f"x: daily insights {day}")
