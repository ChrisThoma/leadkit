"""What other people post that does well, on Reddit and Threads (`leads study`).

A leads pass finds threads to answer. This looks the other way: across the
product's communities, which posts drew the most votes, replies and likes, and
what those posts have in common (format, kind of post, length, timing). It
writes a report a session reads before drafting a post or picking a format.

Reddit: Arctic Shift lists each sub with its scores. A post's score is re-read
about 36 hours after it goes up (the `retrieved_2nd_on` stamp), so posts
younger than MIN_AGE_DAYS are left out; their scores still read 0 or 1. Each
sub is ranked on its own, because a good post in a big sub outscores the best
one in a small one. The "top tenth" is the top 10% of a sub's posts that the
mods left up.

Threads: no API reads other people's posts until Meta approves
keyword_search, so a session runs
the product's searches on the Top tab in Chrome, runs EXTRACT_JS on each, and
feeds the output to `leads study threads FILE`. Rows build up in
study/threads.tsv across runs. Search results don't say how many followers an
author has, so a big account's ordinary post can look like a winner. Read the
top posts' authors before drawing a lesson from them.

The tables are heuristics. They say what to read, not what to conclude: the
last section of each report lists the posts to open and read in full.
"""
import json, math, re, statistics, sys, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from . import arctic, threads

MIN_AGE_DAYS = 2
MAX_PAGES = 30          # 3,000 posts a sub; a busy sub's month is about that
WORKERS = 3
MIN_POSTS = 10          # a sub with fewer live posts gets no top tenth
# No `fields` filter: Arctic Shift refuses most of the ones this needs (is_self, domain,
# removed_by_category, upvote_ratio...), so pages come back whole.

KIND_PATTERNS = [
    ("question", r"\?\s*$|^(what|how|why|which|any|is|are|does|do|can|should|has|have|where|who)\b"),
    ("ask-recs", r"\b(recommend\w*|suggestions?|looking for|alternatives? to|need (an? )?(app|idea)s?)\b"),
    ("i-made", r"\b(i|we) (made|built|created|launched|released|developed|wrote|designed)\b"
               r"|\bmy (first |new |own |little )?(app|game|tool)\b|\bi'?ve been (working|building)\b"),
    ("list", r"^\s*(top )?\d{1,2}\s+\w+|\b\d{1,2} (apps?|ideas|things|ways|tips|games|songs)\b"),
    ("story", r"\b(today|yesterday|last night|this morning|finally|after \d+ (years|months))\b"),
    ("deal", r"\b(free|sale|discount|promo|% off|lifetime)\b"),
]
APP_LINK = r"apps\.apple\.com|play\.google\.com|testflight\.apple\.com"


def kinds(title, body=""):
    """Rough kinds of post from its title (and links in its body). A post can be several."""
    t = title.lower()
    out = [name for name, rx in KIND_PATTERNS if re.search(rx, t)]
    if re.search(APP_LINK, f"{title} {body}", re.I):
        out.append("app-link")
    return out or ["other"]


def reddit_format(x):
    url, domain = x.get("url") or "", (x.get("domain") or "").lower()
    if x.get("is_self"):
        return "text"
    if "/gallery/" in url:
        return "gallery"
    if x.get("is_video") or domain == "v.redd.it" or x.get("post_hint") == "hosted:video":
        return "video"
    if "youtu" in domain or x.get("post_hint") == "rich:video":
        return "youtube"
    if x.get("post_hint") == "image" or domain in ("i.redd.it", "i.imgur.com"):
        return "image"
    return "link"


def length_bucket(n):
    return "short (<50)" if n < 50 else "medium (50-100)" if n <= 100 else "long (>100)"


def body_bucket(n):
    return "none" if n == 0 else "short (<300)" if n < 300 else "medium (300-1500)" if n <= 1500 else "long (>1500)"


def when(ts):
    """Weekday and a four-hour block in this Mac's time zone."""
    d = datetime.fromtimestamp(ts, timezone.utc).astimezone()
    h = d.hour // 4 * 4
    return d.strftime("%a"), f"{h:02d}-{h + 4:02d}"


def reddit_rows(posts, now=None):
    now = now or time.time()
    rows = []
    for x in posts:
        if x.get("stickied") or now - int(x["created_utc"]) < MIN_AGE_DAYS * 86400:
            continue
        body = x.get("selftext") or ""
        if body in ("[removed]", "[deleted]"):
            body = ""
        day, hours = when(int(x["created_utc"]))
        rows.append({
            "id": x["id"], "sub": x["subreddit"], "posted": date.fromtimestamp(int(x["created_utc"])).isoformat(),
            "score": int(x.get("score") or 0), "comments": int(x.get("num_comments") or 0),
            "ratio": x.get("upvote_ratio"), "format": reddit_format(x), "flair": x.get("link_flair_text") or "",
            "kinds": kinds(x.get("title") or "", body + " " + (x.get("url") or "")),
            "title_len": length_bucket(len(x.get("title") or "")), "body_len": body_bucket(len(body)),
            "day": day, "hours": hours, "removed": x.get("removed_by_category") or "",
            "author": x.get("author") or "", "title": (x.get("title") or "").strip(),
            "text": ((x.get("title") or "").strip() + " / " + body.strip()[:300]).strip(" /"),
            "url": f"https://www.reddit.com/r/{x['subreddit']}/comments/{x['id']}/",
        })
    return rows


def mark_winners(rows, key, group="sub"):
    """Flag the top tenth of each group's live posts by `key`, and each post's
    lift: its key over its group's median (a median of 0 counts as 1)."""
    by = defaultdict(list)
    for r in rows:
        r["winner"], r["lift"] = False, 0.0
        if not r.get("removed"):
            by[r.get(group, "")].append(r)
    for live in by.values():
        med = max(statistics.median(r[key] for r in live), 1)
        for r in live:
            r["lift"] = round(r[key] / med, 1)
        if len(live) < MIN_POSTS:
            continue
        for r in sorted(live, key=lambda r: -r[key])[:max(1, round(len(live) / 10))]:
            r["winner"] = True
    return rows


def lifts(rows, field):
    """(value, share of winners, share of all live posts, lift) for each value of
    `field`, most over-represented first. List fields count each item."""
    live = [r for r in rows if not r.get("removed")]
    wins = [r for r in live if r["winner"]]
    if not wins:
        return []

    def tally(rs):
        c = Counter()
        for r in rs:
            v = r[field]
            c.update(v if isinstance(v, list) else [v])
        return c
    w, a = tally(wins), tally(live)
    out = [(v, w[v] / len(wins), a[v] / len(live), (w[v] / len(wins)) / (a[v] / len(live))) for v in a]
    return sorted(out, key=lambda t: (-t[3], -t[2]))


# ---------- Reddit ----------

def fetch_sub(sub, days, get=arctic.get):
    """Live and removed posts in r/<sub> from `days` ago to MIN_AGE_DAYS ago."""
    now = int(time.time())
    since, before, out, seen = now - days * 86400, now - MIN_AGE_DAYS * 86400, [], set()
    for _ in range(MAX_PAGES):
        page = get("posts/search", {"subreddit": sub, "after": since, "before": before, "limit": 100,
                                    "sort": "desc"}) or []
        fresh = [x for x in page if x["id"] not in seen]
        seen.update(x["id"] for x in fresh)
        out += fresh
        if len(page) < 100 or not fresh:
            break
        before = min(int(x["created_utc"]) for x in page) + 1
    return out


def subreddits(p):
    subs = list(p.get("SUBREDDITS", []))
    for g in p.get("GROUPS", []):
        subs += [s for s in g.get("subreddits", []) if s not in subs]
    return subs


def study_reddit(p, days=30, subs=None, get=arctic.get, labels=True, ask=None):
    subs = subs or subreddits(p)
    posts, covered = [], {}

    def one(sub):
        try:
            return sub, fetch_sub(sub, days, get=get)
        except arctic.Error as e:
            print(f"  r/{sub}: {e}", file=sys.stderr)
            return sub, None
    # Three subs at a time: a page of 100 whole posts takes about 9 s, mostly Arctic
    # Shift's. A volunteer service, so no more than that.
    with ThreadPoolExecutor(WORKERS) as pool:
        for sub, got in pool.map(one, subs):
            if got is None:
                continue
            oldest = min((int(x["created_utc"]) for x in got), default=0)
            covered[sub] = (len(got), round((time.time() - oldest) / 86400) if got else 0)
            print(f"  r/{sub}: {len(got)} posts over {covered[sub][1]} days", file=sys.stderr)
            posts += got
    rows = mark_winners(reddit_rows(posts), "score")
    labelled = label(rows, ask=ask or ask_claude) if labels else []
    out = p.dir / "study"
    out.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    write_tsv(out / f"reddit-{stamp}.tsv", rows)
    md = out / f"reddit-{stamp}.md"
    md.write_text(reddit_report(p, rows, covered, days, labelled))
    return md


def reddit_report(p, rows, covered, days, labelled=()):
    live = [r for r in rows if not r["removed"]]
    L = [f"# {p.title}: what does well on Reddit", "",
         f"{date.today().isoformat()}. Posts from the last {days} days, leaving out the last "
         f"{MIN_AGE_DAYS} (their scores aren't final yet). {len(rows)} posts, {len(rows) - len(live)} "
         f"removed by mods or Reddit. Each sub's top tenth is ranked on its own; \"lift\" is a post's "
         f"score over its sub's median.", "", "## The subs", "",
         "| Sub | Posts | Removed | Median score | Top-tenth cutoff | Median comments |", "|---|---|---|---|---|---|"]
    for sub in sorted({r["sub"] for r in rows}, key=lambda s: -len([r for r in live if r["sub"] == s])):
        rs = [r for r in rows if r["sub"] == sub]
        lv = [r for r in rs if not r["removed"]]
        wins = [r["score"] for r in lv if r["winner"]]
        L.append(f"| r/{sub} | {len(rs)} | {pct(len(rs) - len(lv), len(rs))} | "
                 f"{med([r['score'] for r in lv])} | {min(wins) if wins else '-'} | {med([r['comments'] for r in lv])} |")
    # Capped only when the fetch hit the page limit; a quiet sub also covers fewer days.
    short = [s for s, (n, d) in covered.items() if n >= MAX_PAGES * 100 and d < days - MIN_AGE_DAYS - 1]
    if short:
        L += ["", f"Only part of the window was read for {', '.join('r/' + s for s in short)} "
                  f"(the {MAX_PAGES * 100}-post cap)."]
    empty = [s for s, (n, d) in covered.items() if not n]
    if empty:
        L += ["", f"No posts in the window: {', '.join('r/' + s for s in empty)}."]
    L += ["", "## What the top tenth have in common", "",
          "Share of top-tenth posts with each trait, against all live posts. Lift over 1 means the trait "
          "shows up more among the winners. A trait on fewer than 5 winners is noise.", ""]
    for field, label in [("format", "Format"), ("kinds", "Kind of post"), ("title_len", "Title length"),
                         ("body_len", "Body length"), ("day", "Day posted"), ("hours", "Time posted (this Mac's zone)")]:
        L += lift_table(rows, field, label)
    L += hook_section(labelled, lambda r: r["url"])
    L += self_promo(rows)
    L += ["## Top posts by sub", ""]
    for sub in sorted({r["sub"] for r in live}):
        top = sorted([r for r in live if r["sub"] == sub], key=lambda r: -r["score"])[:8]
        L += [f"### r/{sub}", "", "| Score | Comments | Format | Flair | Title |", "|---|---|---|---|---|"]
        L += [f"| {r['score']} | {r['comments']} | {r['format']} | {cell(r['flair'])} | [{cell(r['title'][:90])}]({r['url']}) |"
              for r in top]
        L.append("")
    L += read_next(rows)
    return "\n".join(L) + "\n"


def self_promo(rows):
    """Posts where someone shows their own app: how they score and how often they're removed."""
    mine = [r for r in rows if {"i-made", "app-link"} & set(r["kinds"])]
    L = ["## People showing their own thing", ""]
    if not mine:
        return L + ["None in this window.", ""]
    live = [r for r in mine if not r["removed"]]
    L += [f"{len(mine)} posts say \"I made\" or link a store page. {pct(len(mine) - len(live), len(mine))} were "
          f"removed. The live ones have a median lift of {med([r['lift'] for r in live])} (1 is the sub's median post).", "",
          "| Sub | Posts | Removed | Median lift | Best |", "|---|---|---|---|---|"]
    for sub in sorted({r["sub"] for r in mine}, key=lambda s: -len([r for r in mine if r["sub"] == s])):
        rs = [r for r in mine if r["sub"] == sub]
        lv = sorted([r for r in rs if not r["removed"]], key=lambda r: -r["score"])
        best = f"{lv[0]['score']}: [{cell(lv[0]['title'][:60])}]({lv[0]['url']})" if lv else "-"
        L.append(f"| r/{sub} | {len(rs)} | {pct(len(rs) - len(lv), len(rs))} | {med([r['lift'] for r in lv])} | {best} |")
    L += ["", "The ones that did best, across subs:", "", "| Lift | Score | Comments | Sub | Format | Title |",
          "|---|---|---|---|---|---|"]
    for r in sorted(live, key=lambda r: -r["lift"])[:12]:
        L.append(f"| {r['lift']} | {r['score']} | {r['comments']} | r/{r['sub']} | {r['format']} | "
                 f"[{cell(r['title'][:80])}]({r['url']}) |")
    return L + [""]


def read_next(rows):
    live = [r for r in rows if not r["removed"]]
    mine = sorted([r for r in live if {"i-made", "app-link"} & set(r["kinds"])], key=lambda r: -r["lift"])[:5]
    best = sorted([r for r in live if r["winner"]], key=lambda r: -r["lift"])[:5]
    L = ["## Read these in full", "",
         "The tables can't say why a post worked. Open these with `leads thread URL` and note what the "
         "title promises, what the body opens with, and what the top comments answer to.", ""]
    for r in mine + [r for r in best if r not in mine]:
        L.append(f"- {r['url']} (r/{r['sub']}, {r['score']} points, lift {r['lift']})")
    return L + [""]


# ---------- Threads ----------

# Run on each threads.com search page (Top tab). Scrolls itself and adds each
# post's text lines, counts and media to the tab's sessionStorage, which lasts
# across searches in that tab, and returns only a count (run it with `await` in
# front, or the tool returns {} before it's done). `leads study threads-receive`
# then saves everything gathered; see dump_js.
# Each count is read off its own labelled button: a zero leaves no text.
EXTRACT_JS = r"""(async()=>{const q=new URL(location.href).searchParams.get('q')||'',got=new Map();
const grab=()=>document.querySelectorAll('a[href*="/post/"] time').forEach(t=>{
const a=t.closest('a'),h=a.getAttribute('href').split('?')[0];if(got.has(h))return;
let p=a;for(let i=0;i<12&&p;i++){p=p.parentElement;if(p&&p.innerText&&p.innerText.length>40&&p.querySelectorAll('time').length===1)break;}
if(!p)return;const n={};p.querySelectorAll('svg').forEach(s=>{const l=s.getAttribute('aria-label')||s.querySelector('title')?.textContent;
const b=s.closest('[role=button]');if(['Like','Reply','Repost','Share'].includes(l)&&b)n[l]=b.innerText.trim();});
const imgs=[...p.querySelectorAll('img')].filter(i=>!/profile picture/i.test(i.alt||'')&&i.width>60).length;
const link=[...p.querySelectorAll('a[href^="http"]')].map(x=>x.href).find(x=>!/threads\.(com|net)|instagram\.com/.test(x))||'';
got.set(h,{path:h,date:t.getAttribute('datetime'),lines:p.innerText.split('\n').map(s=>s.trim().slice(0,300)).filter(Boolean).slice(0,14),
likes:n.Like||'',replies:n.Reply||'',reposts:n.Repost||'',shares:n.Share||'',
media:p.querySelector('video')?'video':imgs>1?'carousel':imgs?'image':'',link,query:q});});
for(let i=0;i<8;i++){grab();window.scrollBy(0,innerHeight*1.5);await new Promise(r=>setTimeout(r,1500));}grab();
const all=JSON.parse(sessionStorage.getItem('leadkitStudy')||'[]').concat([...got.values()]);
sessionStorage.setItem('leadkitStudy',JSON.stringify(all));return got.size+' posts from "'+q+'", '+all.length+' gathered';})()"""

# Results out of the page: a tool reading a script's result cuts it at about 1,000
# characters, the clipboard is refused, Threads' content security policy blocks a
# fetch to a local server, and Chrome clears window.name when the tab changes site.
# Its policy sets no form-action, though, so dump_js submits the gathered posts as a
# form to `receive`'s local server. It clears nothing: clearing sessionStorage
# before the save is confirmed would lose the posts. Close the tab after.
def dump_js(url):
    return (r"""(()=>{const s=sessionStorage.getItem('leadkitStudy')||'[]';const f=document.createElement('form');
f.method='POST';f.action='URL';const t=document.createElement('textarea');t.name='posts';t.value=s;f.appendChild(t);
document.body.appendChild(f);f.submit();return JSON.parse(s).length+' posts sent';})()""").replace("URL", url)


def receive(p, port=0, timeout=900):
    """Take one form POST of gathered posts, save it and return its path. Prints
    the URL and the dump script to run on the Threads tab."""
    import http.server, urllib.parse
    out = p.dir / "study"
    out.mkdir(exist_ok=True)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply("leadkit study receiver: run the dump script on the Threads tab")

        def do_POST(self):
            form = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
            try:
                posts = json.loads((form.get("posts") or ["[]"])[0])
            except ValueError:
                return self.reply("not JSON")
            n = len(list(out.glob(f"threads-raw-{date.today().isoformat()}*.json")))
            path = out / f"threads-raw-{date.today().isoformat()}{'-' + str(n + 1) if n else ''}.json"
            path.write_text(json.dumps(posts, ensure_ascii=False))
            got["path"] = path
            self.reply(f"saved {len(posts)} posts to {path}. Close this tab.")

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 5
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"{url}\n# on the Threads tab, run:\n{dump_js(url)}", flush=True)
    deadline = time.time() + timeout
    while "path" not in got and time.time() < deadline:
        server.handle_request()
    server.server_close()
    return got.get("path")


COUNT_LINE = re.compile(r"^[\d.,]+[KM]?$|^\d+ / \d+$|^(Translate|Author|Edited|Top|View activity)$")
DATE_LINE = re.compile(r"^\d+[smhdw]$|^\d\d/\d\d/\d\d$|^\d+ (minutes?|hours?|days?) ago$")


def count(s):
    s = (s or "").replace(",", "").strip()
    if not s:
        return 0
    mult = {"K": 1000, "M": 1000000}.get(s[-1].upper(), 1)
    return int(round(float(s.rstrip("KkMm")) * mult))


def clean_lines(author, lines):
    """The post's own words: drop the author, topic tag, date and count lines."""
    tag, body = "", []
    for i, line in enumerate(lines):
        if i < 4 and line == author:
            continue
        if i < 4 and DATE_LINE.match(line):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if 0 < i < 3 and not body and not tag and len(line) < 40 and DATE_LINE.match(nxt):
            tag = line  # "Tech Threads": the topic tag sits between author and date
            continue
        if COUNT_LINE.match(line):
            continue
        body.append(line)
    return tag, " ".join(body)


def threads_rows(items):
    rows = {}
    for x in items:
        author = x.get("author") or x["path"].split("/")[1].lstrip("@")
        if "lines" in x:
            tag, text = clean_lines(author, x["lines"])
        else:
            tag, text = x.get("tag", ""), x.get("text", "")
        likes, replies, reposts, shares = (count(x.get(k)) for k in ("likes", "replies", "reposts", "shares"))
        r = {"id": x["path"], "path": x["path"], "author": author, "posted": (x.get("date") or "")[:10], "tag": tag,
             "likes": likes, "replies": replies, "reposts": reposts, "shares": shares,
             # Replies and reposts take more than a tap, so they count for more.
             "engagement": likes + 3 * replies + 2 * reposts,
             "media": x.get("media") or "text", "link": "yes" if x.get("link") or re.search(r"https?://|\.\w{2,4}/", text) else "",
             "kinds": kinds(text[:200], text), "length": "short (<100)" if len(text) < 100 else
             "medium (100-300)" if len(text) <= 300 else "long (>300)",
             "query": x.get("query", ""), "text": text[:300]}
        old = rows.get(r["path"])
        if old is None or r["engagement"] > old["engagement"]:
            if old:
                r["query"] = ", ".join(sorted({*old["query"].split(", "), r["query"]} - {""}))
            rows[r["path"]] = r
    return list(rows.values())


def top_tab_urls(p):
    """The product's Threads searches, every one on the Top tab (where winners show)."""
    out = []
    for group, searches in threads.groups(p).items():
        for s in searches:
            query, _tab, tag, *rest = s
            out.append((group, threads.search_url(query, threads.TOP, tag, *rest)))
    return out


def study_threads(p, files=(), labels=True, ask=None):
    out = p.dir / "study"
    out.mkdir(exist_ok=True)
    store = out / "threads.tsv"
    items = [dict(r, kinds=r["kinds"].split(",")) for r in read_tsv(store)]
    for f in files:
        raw = open(f).read().strip()
        new = json.loads(json.loads(raw) if raw.startswith('"') else raw)
        print(f"  {f}: {len(new)} posts", file=sys.stderr)
        items += new
    rows = threads_rows([dict(x, likes=str(x["likes"]), replies=str(x["replies"]), reposts=str(x["reposts"]),
                              shares=str(x["shares"])) if "engagement" in x else x for x in items])
    if not rows:
        raise SystemExit("no Threads posts yet: run the extractor (leads study threads-js) on the "
                         "searches from `leads study threads-urls` and pass its output files")
    write_tsv(store, rows, drop=("winner", "lift"))
    mark_winners(rows, "engagement", group="none")
    labelled = label(rows, ask=ask or ask_claude) if labels else []
    md = out / f"threads-{date.today().isoformat()}.md"
    md.write_text(threads_report(p, rows, labelled))
    return md


def threads_report(p, rows, labelled=()):
    L = [f"# {p.title}: what does well on Threads", "",
         f"{date.today().isoformat()}. {len(rows)} posts from Top-tab searches "
         f"({', '.join(sorted({q for r in rows for q in r['query'].split(', ') if q}))}). Engagement is likes + "
         f"3 × replies + 2 × reposts. The top tenth is ranked across all of them. Follower counts aren't "
         f"known, so check whether a winner is a big account before taking a lesson from it.", "",
         f"Median engagement {med([r['engagement'] for r in rows])}; top-tenth cutoff "
         f"{min([r['engagement'] for r in rows if r['winner']] or [0])}.", "",
         "## What the top tenth have in common", ""]
    for field, label in [("media", "Media"), ("kinds", "Kind of post"), ("length", "Length"), ("link", "Has a link"),
                         ("tag", "Topic tag")]:
        L += lift_table(rows, field, label)
    L += hook_section(labelled, lambda r: threads.BASE + r["path"])
    L += ["## Top posts", "", "| Likes | Replies | Reposts | Media | Author | Post |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -r["engagement"])[:25]:
        L.append(f"| {r['likes']} | {r['replies']} | {r['reposts']} | {r['media']} | @{r['author']} | "
                 f"[{cell(r['text'][:100]) or '(no text)'}]({threads.BASE}{r['path']}) |")
    mine = sorted([r for r in rows if {"i-made", "app-link"} & set(r["kinds"])], key=lambda r: -r["engagement"])
    L += ["", "## People showing their own thing", ""]
    if mine:
        L += [f"{len(mine)} posts say \"I made\" or link a store page; median engagement "
              f"{med([r['engagement'] for r in mine])} against {med([r['engagement'] for r in rows])} overall.", ""]
        L += [f"- {r['engagement']}: @{r['author']}: [{cell(r['text'][:100])}]({threads.BASE}{r['path']})" for r in mine[:10]]
    else:
        L.append("None found.")
    L += ["", "## Read these in full", "",
          "Open the top ten and their replies. Note the first line (that's all the feed shows), whether it "
          "asks for something, and what the replies are answering.", ""]
    return "\n".join(L) + "\n"


# ---------- hooks, read by claude -p ----------

# The title regexes can't tell a joke from a milestone from a hot take, and on
# Threads they put most posts under "other". So a model reads a
# sample and names each post's hook from this fixed list, which keeps runs comparable.
HOOKS = {
    "relatable-humor": "a joke or observation about everyday life that readers recognise",
    "milestone-moment": "a personal moment: a first, a win, a loss, a confession",
    "hot-take": "a strong opinion or a 'you should/shouldn't' statement",
    "crowd-question": "asks readers for their answers, stories or advice",
    "help-request": "a specific problem the poster needs solved",
    "how-to-list": "practical tips, ideas or steps",
    "show-and-tell": "shows something the poster made or did, not for sale",
    "product-pitch": "promotes something for sale or download",
    "news-deal": "news, a release, a sale or an announcement",
    "other": "none of these",
}


def label_sample(rows, cap=120, seed=13):
    """The top tenth (the best `cap`) and as many other live posts picked at random."""
    import random
    live = [r for r in rows if not r.get("removed")]
    wins = sorted([r for r in live if r["winner"]], key=lambda r: -r.get("lift", 0))[:cap]
    rest = [r for r in live if not r["winner"]]
    return wins + random.Random(seed).sample(rest, min(len(wins), len(rest)))


def parse_labels(text):
    out = {}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[0]:
            out[parts[0]] = (parts[1].strip() if parts[1].strip() in HOOKS else "other",
                             parts[2].strip() if len(parts) > 2 else "")
    return out


def ask_claude(prompt, model="sonnet"):
    import subprocess
    out = subprocess.run(["claude", "-p", "--model", model], input=prompt, capture_output=True, text=True, timeout=600)
    if out.returncode:
        raise SystemExit(f"claude -p failed: {out.stderr.strip()[:300]}")
    return out.stdout


def label(rows, ask=ask_claude, model="sonnet", batch=60):
    """Name the hook of each post in label_sample, in batches. Returns the labelled rows."""
    sample = label_sample(rows)
    hooks = "\n".join(f"- {k}: {v}" for k, v in HOOKS.items())
    for i in range(0, len(sample), batch):
        chunk = sample[i:i + batch]
        posts = "\n".join(f"{r['id']}\t{cell(r['text'])[:400]}" for r in chunk)
        prompt = (f"Each line below is a social media post: an id, a tab, then its text. For each one, name its hook, "
                  f"the main reason someone would stop and react to it, from this list:\n{hooks}\n\n"
                  f"Reply with one line per post and nothing else: the id, a tab, the hook name, a tab, "
                  f"and at most eight words on what makes it land.\n\n{posts}\n")
        print(f"  labelling {i + 1}-{i + len(chunk)} of {len(sample)} with claude -p", file=sys.stderr)
        got = parse_labels(ask(prompt, model))
        for r in chunk:
            r["hook"], r["why"] = got.get(r["id"], ("", ""))
    return [r for r in sample if r.get("hook")]


def hook_lifts(labelled):
    """(hook, share of winners, share of the random others, lift) over labelled rows."""
    wins = [r for r in labelled if r["winner"]]
    ctrl = [r for r in labelled if not r["winner"]]
    if not wins or not ctrl:
        return []
    w, c = Counter(r["hook"] for r in wins), Counter(r["hook"] for r in ctrl)
    out = [(h, w[h] / len(wins), c[h] / len(ctrl), (w[h] / len(wins)) / max(c[h] / len(ctrl), 1 / len(ctrl)))
           for h in HOOKS if w[h] or c[h]]
    return sorted(out, key=lambda t: -t[3])


def hook_section(labelled, link):
    if not labelled:
        return []
    wins = sum(r["winner"] for r in labelled)
    L = ["## Hooks", "",
         f"claude -p named the hook of {wins} top-tenth posts and {len(labelled) - wins} others picked at random. "
         "Lift is how much more often a hook shows up among the winners than among the others "
         "(a hook no random post had counts as one of them).", "",
         "| Hook | Top tenth | Others | Lift |", "|---|---|---|---|"]
    L += [f"| {h} | {w:.0%} | {c:.0%} | {lift:.1f} |" for h, w, c, lift in hook_lifts(labelled)]
    L += ["", "What makes the winners land, by hook:", ""]
    by = defaultdict(list)
    for r in sorted((r for r in labelled if r["winner"]), key=lambda r: -r.get("lift", 0)):
        by[r["hook"]].append(r)
    for h, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        L.append(f"**{h}** ({len(rs)})")
        L += [f"- {cell(r['why'])}: [{cell(r['text'][:70])}]({link(r)})" for r in rs[:6]]
        L.append("")
    return L


# ---------- shared ----------

def lift_table(rows, field, label):
    table = lifts(rows, field)
    if not table:
        return []
    wins = sum(1 for r in rows if r.get("winner"))
    L = [f"**{label}**", "", "| | Top tenth | All | Lift |", "|---|---|---|---|"]
    for v, w, a, lift in table:
        if a < 0.02 and w == 0:
            continue
        flag = "" if w * wins >= 5 else " (few)"
        L.append(f"| {cell(str(v)) or '(none)'} | {w:.0%} | {a:.0%} | {lift:.1f}{flag} |")
    return L + [""]


def med(xs):
    return round(statistics.median(xs), 1) if xs else "-"


def pct(n, d):
    return f"{n / d:.0%}" if d else "-"


def cell(s):
    return (s or "").replace("|", "/").replace("\n", " ")


def write_tsv(path, rows, drop=()):
    if not rows:
        return
    cols = [k for k in rows[0] if k not in drop]
    with open(path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(",".join(v) if isinstance(v, list) else cell(str(v)).replace("\t", " ")
                              for v in (r[c] for c in cols)) + "\n")


def read_tsv(path):
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    cols = lines[0].split("\t")
    return [dict(zip(cols, line.split("\t"))) for line in lines[1:] if line]
