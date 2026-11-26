"""Threads: the searches a leads pass runs in Chrome, marking posted replies,
and the official keyword_search API watcher.

The API has no feed (`leads threads-feed` reads the home feed in Chrome), so passes run the
product's THREADS_SEARCHES in Chrome (Claude in Chrome) and read the results
with EXTRACT_JS. Generic phrases also match months-old viral posts, so skip
anything older than about a day.

When posting, type the prose and paste the store link: a typed URL only links
"https://apps.apple", and leaves a dead link. Replies that carry media
need ATTACH_JS first: Threads' "Attach media" button opens a system file
picker, which ATTACH_JS stops, leaving the file input in the page for Claude in
Chrome's file_upload. A page fetch from a local server is blocked by Threads'
content security policy, so don't try that.
"""
import json, os, plistlib, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import kinds, product, reddit, threadsapi, tsv
from .product import settings

TOP, RECENT = "", "&filter=recent"
BASE = "https://www.threads.com"


def search_url(query, tab, tag, tag_id=None):
    """A search, a tag search, or a community feed (a tag with its tag_id)."""
    return (f"{BASE}/search?q={quote(query)}" + ("&serp_type=tags" if tag else "")
            + (f"&tag_id={tag_id}" if tag_id else "") + tab)


def groups(p):
    """The product's own (domain) search groups, then the shared app-kind ones."""
    table = dict(p.need("THREADS_SEARCHES"))
    if kinds.enabled(p):
        for name, group in kinds.APP["threads"].items():
            table.setdefault(name, group)
    return table


def kind_of(p, group):
    own = p.get("THREADS_SEARCHES", {})
    return kinds.APP_KIND if group in kinds.APP["threads"] and group not in own else kinds.DOMAIN


def searches(p, groups_wanted=()):
    """Print the search URLs, one group at a time, each headed by its kind."""
    table = groups(p)
    for g in [g for g in groups_wanted if g in table] or list(table):
        label = ("app: posts under a day old; the reply is the pitch, with media"
                 if kind_of(p, g) == kinds.APP_KIND else "domain")
        print(f"# {g} ({label})")
        for search in table[g]:
            print(search_url(*search))


# Run with the reply composer open. Intercepts the file input's click so no
# system picker opens, then presses "Attach media".
ATTACH_JS = r"""(async()=>{if(!window.__clickPatched){const orig=HTMLInputElement.prototype.click;
HTMLInputElement.prototype.click=function(){if(this.type==='file'){window.__lastFileInput=this;return;}return orig.call(this);};
window.showOpenFilePicker=async()=>{throw new DOMException('blocked','AbortError');};window.__clickPatched=true;}
[...document.querySelectorAll('[aria-label="Attach media"]')].pop().click();
await new Promise(r=>setTimeout(r,800));return document.querySelectorAll('input[type=file]').length+' file input(s)';})()"""

# Paste into the page after scrolling. Lists each post once: date, path, the
# first 120 characters. The page's own text dump leaves the results out. The
# first line names the search, so whoever logs a lead has its query to hand
# (`leads set URL query=...`).
EXTRACT_JS = r"""(()=>{const seen=new Set(),out=[];
document.querySelectorAll('a[href*="/post/"] time').forEach(t=>{
const a=t.closest('a'),h=a.getAttribute('href');if(seen.has(h))return;seen.add(h);
let c=a;for(let i=0;i<12&&c;i++){c=c.parentElement;
if(c&&c.innerText&&c.innerText.length>60&&c.querySelectorAll('time').length===1)break;}
out.push(t.getAttribute('datetime').slice(5,13)+' '+h+' | '+(c?c.innerText:'').replace(/\s+/g,' ').slice(0,120));});
const u=new URLSearchParams(location.search),q=u.get('q');
if(q)out.unshift('# search: '+q+' ('+(u.get('filter')==='recent'?'recent':'top')+(u.get('serp_type')==='tags'?', tag':'')+')');
return out.join('\n');})()"""


def replies_js():
    """Run on threads.com/@<account>/replies (scroll a screen or two first; the
    list unloads what scrolls far off). Prints "parent-path reply-path text" per
    reply, the input `leads threads-posted` reads. The text is the reply's own
    words and link targets, so each product only takes the replies that name it."""
    me = f"/@{settings.THREADS_ACCOUNT}/"
    return (r"""(()=>{const seen=new Set(),paths=[],text={};
document.querySelectorAll('a[href*="/post/"] time').forEach(t=>{
const a=t.closest('a'),h=a.getAttribute('href');if(seen.has(h))return;seen.add(h);paths.push(h);
let c=a;for(let i=0;i<12&&c;i++){c=c.parentElement;
if(c&&c.innerText&&c.innerText.length>60&&c.querySelectorAll('time').length===1)break;}
text[h]=c?(c.innerText+' '+[...c.querySelectorAll('a[href]')].map(l=>l.href).join(' ')).replace(/\s+/g,' '):'';});
const out=[];for(let i=1;i<paths.length;i++){
if(paths[i].startsWith('ME')&&!paths[i-1].startsWith('ME'))out.push(paths[i-1]+' '+paths[i]+' '+text[paths[i]]);}
return out.join('\n');})()""").replace("ME", me)


def media(p):
    return {k: p.repo_path(v) for k, v in p.get("THREADS_MEDIA", {}).items()}


def path_of(url):
    return url.replace(BASE, "").split("?")[0].rstrip("/")


def names_product(p, text):
    """Whether a reply's text or link targets name this product."""
    text = text.lower()
    store_id = p.get("APP_STORE_ID")
    return p.title.lower() in text or bool(store_id and f"id{store_id}" in text)


def logged_by_others(p, others=None):
    """{thread path: app title} for threads another product has also logged."""
    if others is None:
        others = [o for o in product.everything() if o.name != p.name]
    shared = {}
    for o in others:
        if o.threads_tsv.exists():
            for r in tsv.read(o.threads_tsv)[1]:
                shared.setdefault(path_of(r.get("url") or ""), o.title)
    return shared


def mark_posted(p, items, others=None):
    """Mark Threads rows posted.

    Each item is either "parent-path reply-path [reply text]" (from replies_js,
    which also records the reply's link) or a single post URL or path, for a
    reply found by hand on the Replies tab. When the text is there, a reply
    counts only if it names this product or links its App Store id, so one app's
    reply on a showcase thread doesn't mark another app's draft there posted.
    Without the text, a reply on a thread another product also logged isn't
    marked, since it can't tell which app's reply it is.
    """
    replies, plain = {}, set()
    shared = None
    for item in items:
        parts = item.split(maxsplit=2)
        if not parts:
            continue
        if len(parts) == 3 and not names_product(p, parts[2]):
            print(f"not {p.title}: {BASE}{parts[1]}", file=sys.stderr)
            continue
        if len(parts) < 3:
            shared = logged_by_others(p, others) if shared is None else shared
            other = shared.get(path_of(parts[0]))
            if other:
                print(f"not marked: {other} also logged {BASE}{path_of(parts[0])}. Pass the reply's text, "
                      f"or mark the right app's row with `leads set`.", file=sys.stderr)
                continue
        if len(parts) >= 2:
            replies[path_of(parts[0])] = BASE + parts[1]
        else:
            plain.add(path_of(parts[0]))

    def update(r):
        path = path_of(r["url"])
        if path in replies and tsv.status(r) in ("posted", "replied") and "Reply:" not in (r.get("notes") or ""):
            # Marked replied on the drafts page: keep the status, record where the reply is.
            r["notes"] = f"Reply: {replies[path]} {r.get('notes') or ''}".strip()
            return True
        if path in replies and tsv.status(r) in tsv.OPEN | {"skip"}:
            r["status"] = "posted"
            r["notes"] = f"Reply: {replies[path]} {r.get('notes') or ''}".strip()
            return True
        if path in plain and tsv.status(r) in tsv.OPEN:
            r["status"] = "posted"
            return True
        return False
    changed = tsv.rewrite(p.threads_tsv, update)
    for r in changed:
        label = r.get("title") or (r.get("author") and f"@{r['author']}") or r["url"]
        print(f"posted: {p.title}: {label}", file=sys.stderr)
    return changed


# The official API: Meta's keyword_search allows 2,200 searches a rolling day,
# sorts by RECENT and filters by date, where driving threads.com stalls after
# about ten searches. It needs an approved app and a token; until the app is
# approved it silently searches only the token owner's own posts.
API = "https://graph.threads.net/v1.0/keyword_search"
# Pages per query. A broad keyword over --days can run past one page of 100,
# and stopping at the first page dropped older posts while reporting a clean
# pass. The cap keeps one noisy query from eating the daily search quota.
MAX_PAGES = 5
FIELDS = ["found", "posted", "priority", "author", "url", "engagement", "pitch", "reply", "notes", "status", "kind", "query"]
# The API's ids: `id` is the lead's post, which a reply needs; `reply_id` is
# ours, which a delete needs. Chrome-found rows have neither.
ID_FIELDS = ["id", "reply_id"]

# Older notes record the search as free text. These are the forms they used:
# Search "x", Found by 'x', Found by Top search "x", and "x" tag Recent.
_Q = r"""(?:"([^"]+)"|\u201c([^\u201d]+)\u201d|'([^']+)'(?!\w)|\u2018([^\u2019]+)\u2019)"""
_NOTE_SEARCH = re.compile(r"\b(?:search|found by)\s+" + _Q, re.I)
_NOTE_TAG = re.compile(r"^\s*" + _Q + r"\s+tag\b", re.I)
_NOTE_COMMUNITY = re.compile(r"\b([A-Z][A-Za-z]*) Threads\b")  # "Baking Threads", not "on Threads"
_NOT_COMMUNITIES = {"Meta", "Top", "Recent", "Search"}


def _group_name(q):
    """One spelling per search: lowercase, no `tag:`, and a community's name
    closed up (notes say `Baking Threads`, the extractor `bakingthreads`)."""
    q = re.sub(r"^tag:\s*", "", q.strip().lower())
    return re.sub(r"^(\w+) threads$", r"\1threads", q)


def query_of(row):
    """The search that found a lead, normalised for grouping: the `query`
    column, else read from the older notes, else ''. Files aren't backfilled;
    reports derive it."""
    q = _group_name(row.get("query") or "")
    if q:
        return q
    notes = row.get("notes") or ""
    for pat in (_NOTE_SEARCH, _NOTE_TAG):
        m = pat.search(notes)
        if m:
            return _group_name(next(g for g in m.groups() if g))
    for m in _NOTE_COMMUNITY.finditer(notes):
        if m.group(1) not in _NOT_COMMUNITIES:
            return _group_name(f"{m.group(1)} threads")
    return ""


def token_file(p=None):
    # One Meta app and one account token serve every product, so p can be None.
    return Path(os.path.expanduser((p.get("THREADS_TOKEN_FILE") if p else None) or "~/.config/leadkit/threads_token"))


def token(p=None):
    f = token_file(p)
    t = os.environ.get("THREADS_ACCESS_TOKEN") or (f.read_text().strip() if f.exists() else "")
    if not t:
        sys.exit(f"no token: set THREADS_ACCESS_TOKEN or write it to {f} (see README.md)")
    return t


def refresh(p, tok):
    # Long-lived tokens last 60 days and can be refreshed once a day after
    # they're a day old, so running this weekly keeps the watcher alive.
    qs = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": tok})
    with urllib.request.urlopen(f"https://graph.threads.net/refresh_access_token?{qs}", timeout=30) as r:
        data = json.load(r)
    f = token_file(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(data["access_token"])
    f.chmod(0o600)
    print(f"refreshed; expires in {data.get('expires_in', 0) // 86400} days", file=sys.stderr)


# The use case's User Token Generator grants a fixed set that leaves out
# keyword_search, manage_mentions and delete (2026-10-30), so tokens come from
# the sign-in page, which grants what it's asked for.
SCOPES = ["threads_basic", "threads_keyword_search", "threads_content_publish", "threads_manage_replies",
          "threads_read_replies", "threads_manage_mentions", "threads_manage_insights", "threads_delete"]
SECRET_FILE = Path(os.path.expanduser("~/.config/leadkit/threads_app_secret"))


def authorize_url(state=None):
    """The Threads sign-in. A state of "<port>.<nonce>" sends the browser on from
    the site's callback page to the local Threads page that asked."""
    q = {"client_id": settings.THREADS_APP_ID, "redirect_uri": settings.THREADS_REDIRECT,
         "scope": ",".join(SCOPES), "response_type": "code"}
    return "https://threads.net/oauth/authorize?" + urllib.parse.urlencode(q | ({"state": state} if state else {}))


def login_code(pasted):
    """The code from the address Threads redirected to, or a bare code."""
    pasted = pasted.strip().split("#")[0]
    return urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [pasted])[0]


def exchange(code):
    """Trade a sign-in code for a 60-day token: {"access_token", "expires_in"}."""
    secret = os.environ.get("THREADS_APP_SECRET") or (SECRET_FILE.read_text().strip() if SECRET_FILE.exists() else "")
    if not secret:
        raise ValueError(f"no app secret: put the Threads app secret in {SECRET_FILE} (chmod 600) or THREADS_APP_SECRET")
    form = urllib.parse.urlencode({"client_id": settings.THREADS_APP_ID, "client_secret": secret,
                                   "grant_type": "authorization_code", "redirect_uri": settings.THREADS_REDIRECT,
                                   "code": code}).encode()
    try:
        with urllib.request.urlopen("https://graph.threads.net/oauth/access_token", form, timeout=30) as r:
            short = json.load(r)["access_token"]
        qs = urllib.parse.urlencode({"grant_type": "th_exchange_token", "client_secret": secret, "access_token": short})
        with urllib.request.urlopen(f"https://graph.threads.net/access_token?{qs}", timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # A code works once and expires within the hour.
        raise ValueError(f"{e.code}: {e.read().decode(errors='replace')[:300]}") from None


def save_token(p, data):
    f = token_file(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(data["access_token"])
    f.chmod(0o600)
    return f


def login(p, pasted=None):
    """With nothing pasted, print the sign-in URL. With the redirect address,
    trade its code for a 60-day token and save it where token() reads it."""
    if not pasted:
        print(authorize_url())
        print(f"approve as {settings.THREADS_ACCOUNT}, then: leads threads-login '<the address it lands on>'", file=sys.stderr)
        return
    try:
        data = exchange(login_code(pasted))
    except ValueError as e:
        sys.exit(str(e))
    f = save_token(p, data)
    print(f"saved {f}; expires in {data.get('expires_in', 0) // 86400} days", file=sys.stderr)


def api_search(q, mode, since, tok, pause):
    params = {
        "q": q, "search_type": "RECENT", "search_mode": mode, "since": str(since), "limit": "100",
        "fields": "id,text,permalink,timestamp,username,is_reply,has_replies,is_quote_post",
        "access_token": tok,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    posts = []
    for page in range(MAX_PAGES):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            print(f"  {e.code} for {q!r}: {body}", file=sys.stderr)
            if e.code in (400, 401, 403) and "OAuth" in body:
                sys.exit("token rejected or expired; refresh it (README.md)")
            # Code 10 on every keyword: the token was issued without the
            # threads_keyword_search scope (2026-10-30), so every query would fail the same way.
            if e.code == 403 and '"code":10' in body:
                sys.exit("token lacks threads_keyword_search; regenerate it with that permission granted")
            return posts
        finally:
            time.sleep(pause)
        posts += data.get("data", [])
        url = (data.get("paging") or {}).get("next")
        if not url:
            return posts
    print(f"  {q!r}: stopped after {MAX_PAGES} pages; older matches may be missing", file=sys.stderr)
    return posts


def api_score(p, text):
    """The Reddit table plus THREADS_EXTRA: Threads posts have no title and run
    short, so a bare question is worth a point the Reddit table never needed to give."""
    s, hits = reddit.score(p, text)
    for pat, w in p.get("THREADS_EXTRA", {}).items():
        if re.search(pat, text.lower()):
            s += w
            hits.append(pat)
    return s, hits


def api_watch(p, days=3, pause=1.0, dry_run=False, include_replies=False, min_score=None, refresh_token=False):
    keywords, tags = p.need("THREADS_KEYWORDS"), p.get("THREADS_TAGS", [])
    min_score = p.get("THREADS_MIN_SCORE", p.need("MIN_SCORE")) if min_score is None else min_score
    tok = token(p)
    if refresh_token:
        return refresh(p, tok)
    seen = {r["url"] for r in tsv.read(p.threads_tsv)[1]}
    own = {settings.THREADS_ACCOUNT}
    now = datetime.now(timezone.utc)
    since = int((now - timedelta(days=days)).timestamp())
    found, maybe, authors = {}, [], set()
    hook = p.get("threads_row", lambda row, text: row)

    for q, mode in [(k, "KEYWORD") for k in keywords] + [(t, "TAG") for t in tags]:
        posts = api_search(q, mode, since, tok, pause)
        print(f"{mode.lower():7} {q!r}: {len(posts)}", file=sys.stderr)
        for post in posts:
            authors.add(post.get("username", ""))
            url = post.get("permalink", "")
            text = post.get("text") or ""
            if not url or url in seen or url in found or post.get("username", "").lower() in own:
                continue
            if post.get("is_reply") and not include_replies:
                continue
            s, _ = api_score(p, text)
            row = hook({
                "found": now.date().isoformat(),
                "posted": (post.get("timestamp") or "")[:10],
                "author": post.get("username", ""),
                "url": url,
                "notes": f"[watch {s}] " + text[:280].replace("\t", " ").replace("\n", " ").strip(),
                "status": "new",
                "id": post.get("id", ""),
                "query": q if mode == "KEYWORD" else f"tag:{q}",
            }, text)
            if s >= min_score:
                found[url] = row | {"_score": s}
            elif s >= 2:
                maybe.append(row | {"_score": s})

    # An app not yet approved for threads_keyword_search silently searches only
    # the token owner's own posts, which looks like a quiet day, not an error.
    if authors and authors <= own | {""}:
        print("every result is our own post: the app isn't approved for threads_keyword_search yet", file=sys.stderr)

    rows = sorted(found.values(), key=lambda r: -r["_score"])
    for r in rows:
        print(f"[{r['_score']:>2}] @{r['author']} {r['posted']}  {r['notes'][:140]}\n      {r['url']}")
    print(f"{len(rows)} new lead(s)", file=sys.stderr)
    if maybe:
        print("\nnear misses (not added):")
        for r in sorted(maybe, key=lambda r: -r["_score"])[:40]:
            print(f"[{r['_score']:>2}] @{r['author']} {r['posted']}  {r['notes'][:140]}\n      {r['url']}")
    if dry_run:
        return rows
    # Anyone who mentions your Threads account is a lead whatever they wrote.
    for r in add_mentions(p, tok):
        print(f"mention: @{r['author']} {r['url']}", file=sys.stderr)
    if not rows:
        return rows
    tsv.ensure(p.threads_tsv, ["query"] + ID_FIELDS)
    tsv.append(p.threads_tsv, rows, FIELDS + ID_FIELDS)
    print(f"appended to {p.threads_tsv}", file=sys.stderr)
    return rows


# The API features behind the Threads page and the drafts page's buttons. Each
# one runs because you pressed something; nothing here runs on a timer.

def add_lead(p, post, how):
    """Append a post from search or mentions as a `new` lead, keeping its id.
    Our own posts and ones already in the file are left out (None)."""
    url = post.get("permalink", "")
    if not url or (post.get("username") or "").lower() == settings.THREADS_ACCOUNT:
        return None
    if url in {r["url"] for r in tsv.read(p.threads_tsv)[1]}:
        return None
    text = (post.get("text") or "").replace("\t", " ").replace("\n", " ").strip()
    row = {"found": datetime.now(timezone.utc).date().isoformat(), "posted": (post.get("timestamp") or "")[:10],
           "author": post.get("username", ""), "url": url, "notes": f"[{how}] {text[:280]}", "status": "new",
           "id": post.get("id", "")}
    tsv.ensure(p.threads_tsv, ID_FIELDS)
    tsv.append(p.threads_tsv, [row], FIELDS + ID_FIELDS)
    return row


def add_mentions(p, tok):
    return [r for r in (add_lead(p, m, "mention") for m in threadsapi.mentions(tok)) if r]


def _reply_text(r):
    reply = (r.get("reply") or "").strip()
    return reply[1:-1].strip() if len(reply) > 1 and reply[0] == reply[-1] == '"' else reply


def _row(p, url):
    for r in tsv.read(p.threads_tsv)[1]:
        if r["url"] == url:
            return r
    raise ValueError(f"no Threads lead {url}")


# Threads counts links too; the drafts page warns at the same length.
REPLY_LIMIT = 500


def reply_to_lead(p, url, tok):
    """Publish the lead's drafted reply under its post, then mark it posted with our reply's link."""
    r = _row(p, url)
    text = _reply_text(r)
    if tsv.status(r) not in tsv.OPEN or not text:
        raise ValueError("no open draft to post")
    if not r.get("id"):
        raise ValueError("found in Chrome, so there's no post id to reply to; copy the reply instead")
    if len(text) > REPLY_LIMIT:
        raise ValueError(f"{len(text)} characters, over {REPLY_LIMIT}")
    ours = threadsapi.publish(tok, text, reply_to=r["id"])
    tsv.ensure(p.threads_tsv, ID_FIELDS)

    def update(row):
        if row["url"] != url:
            return False
        row["status"], row["reply_id"] = "posted", ours["id"]
        row["notes"] = f"Reply: {ours['permalink']} {row.get('notes') or ''}".strip()
        return True
    tsv.rewrite(p.threads_tsv, update)
    return ours


def delete_reply(p, url, tok):
    """Delete the reply we posted on this lead (one with a dead link, say)."""
    r = _row(p, url)
    if not r.get("reply_id"):
        raise ValueError("no reply of ours recorded on this lead")
    threadsapi.delete(tok, r["reply_id"])

    def update(row):
        if row["url"] != url:
            return False
        row["status"], row["reply_id"] = "deleted", ""
        row["notes"] = f"Reply deleted {datetime.now(timezone.utc).date()}. {row.get('notes') or ''}".strip()
        return True
    tsv.rewrite(p.threads_tsv, update)


INSIGHTS_FIELDS = ["date", "posted", "url", "text"] + threadsapi.METRICS
# One account posts for every app, so its numbers are leadkit's, not a product's.
INSIGHTS_TSV = product.DATA / "threads-insights.tsv"
# One row per reply of ours, with its views, so `leads threads-yield` can say
# which searches found threads worth replying to.
REPLIES_FIELDS = ["posted", "url", "id", "text", "views", "likes", "replies", "reposts", "quotes", "read"]
REPLIES_TSV = product.DATA / "threads-replies.tsv"
INSIGHTS_LABEL = "local.leadkit.threads-insights"
INSIGHTS_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{INSIGHTS_LABEL}.plist"
INSIGHTS_LOG = Path.home() / "Library" / "Logs" / "leadkit-threads-insights.log"


def log_insights(tok, path, limit=25):
    """One row per recent post per day, so views can sit next to the day's sales,
    and a new post can be held against older ones at the same age (date - posted).
    A second run on the same day replaces that day's rows."""
    today = datetime.now(timezone.utc).date().isoformat()
    rows = []
    for post in threadsapi.own_posts(tok, limit):
        if not post.get("text"):  # reposts of other posts: no text, no insights
            continue
        m = threadsapi.insights(tok, post["id"])
        rows.append({"date": today, "posted": (post.get("timestamp") or "")[:16].replace("T", " "),
                     "url": post.get("permalink", ""),
                     "text": post["text"].replace("\t", " ").replace("\n", " ")[:80],
                     **{k: m.get(k, "") for k in threadsapi.METRICS}})
    kept = [r for r in tsv.read(path)[1] if r["date"] != today]
    tsv.write(path, INSIGHTS_FIELDS, kept + rows)
    return rows


def log_reply_insights(tok, path, fresh_days=14):
    """Keep one row per reply of ours in `path`, upserted by url, newest first.
    Only replies not in the file yet, or posted within `fresh_days`, are asked
    for insights: older views have settled, and a daily run stays at a few
    requests. The first run on an empty file backfills everything. A reply whose
    insights call fails keeps its old row, or none. Returns the rows refreshed."""
    today = datetime.now(timezone.utc).date().isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=fresh_days)).strftime("%Y-%m-%d %H:%M")
    kept = {r["url"]: r for r in tsv.read(path)[1]}
    refreshed = []
    for reply in threadsapi.own_replies(tok):
        url = reply.get("permalink", "")
        posted = (reply.get("timestamp") or "")[:16].replace("T", " ")
        if not url or (url in kept and posted < cutoff):
            continue
        try:
            m = threadsapi.insights(tok, reply["id"])
        except threadsapi.ApiError as e:
            print(f"insights for reply {reply['id']} skipped: {e}", file=sys.stderr)
            continue
        row = {"posted": posted, "url": url, "id": reply["id"],
               "text": (reply.get("text") or "").replace("\t", " ").replace("\n", " ")[:80],
               **{k: m.get(k, "") for k in threadsapi.METRICS}, "read": today}
        kept[url] = row
        refreshed.append(row)
    tsv.write(path, REPLIES_FIELDS, sorted(kept.values(), key=lambda r: r["posted"], reverse=True))
    return refreshed


def insights_plist(hour, minute, home, python, log):
    return plistlib.dumps({
        "Label": INSIGHTS_LABEL,
        "ProgramArguments": [python, "-m", "leadkit.cli", "threads-insights", "--scheduled"],
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
    hour, minute = (int(x) for x in at.split(":"))
    INSIGHTS_PLIST.write_bytes(insights_plist(hour, minute, Path(__file__).resolve().parents[1],
                                              sys.executable, INSIGHTS_LOG))
    subprocess.run(["launchctl", "bootstrap", domain, str(INSIGHTS_PLIST)], check=True)
    print(f"daily Threads insights at {at}: {INSIGHTS_PLIST}\nlog: {INSIGHTS_LOG}")


def scheduled_insights(day=None):
    """What the daily job runs: keep the 60-day token alive, log, commit the TSV (no push)."""
    from . import aso_cli
    tok = token()
    try:
        refresh(None, tok)  # allowed once the token is a day old; a fresh one just says no
        tok = token()
    except Exception as e:  # noqa: BLE001
        print(f"token not refreshed: {e}", file=sys.stderr)
    log_insights(tok, INSIGHTS_TSV)
    try:
        log_reply_insights(tok, REPLIES_TSV)
    except Exception as e:  # noqa: BLE001  the posts log is already written; commit it anyway
        print(f"reply insights failed: {e}", file=sys.stderr)
    day = day or datetime.now().date().isoformat()
    aso_cli.commit_ranks(INSIGHTS_TSV.parent, [INSIGHTS_TSV, REPLIES_TSV], day, message=f"threads: daily insights {day}")
