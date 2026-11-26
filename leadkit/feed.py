"""Threads home feed: scroll your For You or Following feed in Claude in Chrome
and list the posts in the terminal, so a leads pass can pick ones to reply to.

The official API has no feed endpoint, so this reads the page. Threads drops
posts from the page as it scrolls, so FEED_JS collects while it scrolls and keeps
what it found in the tab's sessionStorage; run it as often as you like, then
`leads threads-feed receive` takes everything gathered (a script can only hand
back about 1,000 characters, see study.dump_js) and prints the new posts.
The feed is the same for every app, so it isn't tied to a product. Raw dumps
hold other people's posts and stay out of git.
"""
import json, re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from . import study
from .product import DATA, PRODUCTS, settings

BASE = "https://www.threads.com"
FEEDS = {"for-you": f"{BASE}/for_you", "following": f"{BASE}/following"}
OUT = DATA / "marketing" / "threads-feed"
KEY = "leadkitFeed"
ME = settings.THREADS_ACCOUNT

# Run with `await` on a feed page. Scrolls about 25 seconds, adds each post to
# the tab's sessionStorage (merged by path) and returns only counts.
FEED_JS = r"""(async()=>{const feed=location.pathname.replace(/\//g,'')||'home',got=new Map();
const grab=()=>document.querySelectorAll('a[href*="/post/"] time').forEach(t=>{
const a=t.closest('a'),h=a.getAttribute('href').split('?')[0];if(got.has(h))return;
let p=a;for(let i=0;i<12&&p;i++){p=p.parentElement;if(p&&p.innerText&&p.innerText.length>40&&p.querySelectorAll('time').length===1)break;}
if(!p)return;const n={};p.querySelectorAll('svg').forEach(s=>{const l=s.getAttribute('aria-label')||s.querySelector('title')?.textContent;
const b=s.closest('[role=button]');if(['Like','Reply','Repost','Share'].includes(l)&&b)n[l]=b.innerText.trim();});
const imgs=[...p.querySelectorAll('img')].filter(i=>!/profile picture/i.test(i.alt||'')&&i.width>60).length;
got.set(h,{path:h,date:t.getAttribute('datetime'),lines:p.innerText.split('\n').map(s=>s.trim().slice(0,400)).filter(Boolean).slice(0,16),
likes:n.Like||'',replies:n.Reply||'',reposts:n.Repost||'',shares:n.Share||'',
media:p.querySelector('video')?'video':imgs>1?'carousel':imgs?'image':'',query:feed});});
for(let i=0;i<16;i++){grab();window.scrollBy(0,innerHeight*1.5);await new Promise(r=>setTimeout(r,1500));}grab();
const all=new Map(JSON.parse(sessionStorage.getItem('KEY')||'[]').map(x=>[x.path,x]));const before=all.size;
got.forEach((v,k)=>all.set(k,v));sessionStorage.setItem('KEY',JSON.stringify([...all.values()]));
return got.size+' posts seen on '+feed+', '+(all.size-before)+' new, '+all.size+' gathered';})()""".replace("KEY", KEY)


def code(url_or_path):
    m = re.search(r"/post/([\w-]+)", url_or_path or "")
    return m.group(1) if m else None


def logged_codes(products_dir=PRODUCTS):
    """Every post already in some product's Threads leads TSV."""
    codes = set()
    for tsv in Path(products_dir).glob("*/**/threads-leads.tsv"):
        codes.update(c for c in map(code, re.findall(r"https://www\.threads\.\w+/\S+", tsv.read_text())) if c)
    return codes


def earlier_codes(out, latest):
    codes = set()
    for f in Path(out).glob("feed-*.json"):
        if f != latest:
            codes.update(code(x.get("path")) for x in json.loads(f.read_text()))
    return codes


def age(posted, now):
    try:
        h = (now - datetime.fromisoformat(posted.replace("Z", "+00:00"))).total_seconds() / 3600
    except (ValueError, AttributeError):
        return "?", 1e9
    return (f"{int(h * 60)}m" if h < 1 else f"{int(h)}h" if h < 48 else f"{int(h // 24)}d"), h


def report(path, out=OUT, products_dir=PRODUCTS, everything=False, max_hours=48, now=None):
    """Lines for the posts in one dump, newest first: leaves out your own posts,
    posts already logged as leads, ones listed by an earlier dump and old ones."""
    now = now or datetime.now(timezone.utc)
    items = json.loads(Path(path).read_text())
    dates = {x["path"]: x.get("date", "") for x in items}
    logged, earlier = logged_codes(products_dir), set() if everything else earlier_codes(out, Path(path))
    rows, skipped = [], {"mine": 0, "logged": 0, "listed before": 0, "old": 0}
    for r in study.threads_rows(items):
        c = code(r["path"])
        why = ("mine" if r["author"] == ME else "logged" if c in logged else
               "listed before" if c in earlier else None)
        label, hours = age(dates.get(r["path"]), now)
        if not why and not everything and hours > max_hours:
            why = "old"
        if why:
            skipped[why] += 1
            continue
        rows.append((hours, label, r))
    rows.sort(key=lambda x: x[0])
    lines = []
    for _, label, r in rows:
        counts = f"{r['likes']} likes, {r['replies']} replies" + (f", {r['media']}" if r["media"] != "text" else "")
        lines += [f"{label:>4}  @{r['author']}  ({counts}) {r['query']}", f"      {BASE}{r['path']}",
                  f"      {r['text'][:280]}", ""]
    gone = ", ".join(f"{n} {k}" for k, n in skipped.items() if n)
    lines.append(f"# {len(rows)} posts" + (f" (left out: {gone})" if gone else ""))
    return lines


def receive(port=0, timeout=900):
    OUT.mkdir(parents=True, exist_ok=True)
    return study.receive(SimpleNamespace(dir=OUT), port=port, timeout=timeout, key=KEY, out=OUT, prefix="feed")


def guide():
    return [f"# 1. open {FEEDS['for-you']} (or {FEEDS['following']}) in Claude in Chrome",
            "# 2. run `leads threads-feed --js` there with await; repeat to read further down",
            "# 3. `leads threads-feed receive` (in the background), then run the script it prints on the tab"]
