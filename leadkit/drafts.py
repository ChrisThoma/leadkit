"""The reply drafts waiting to be posted, as one page in Chrome.

Reads each product's reddit-leads.tsv and threads-leads.tsv and shows every
row with a written reply that is not yet posted or skipped, best priority
first, each with a link to the thread, a button that copies the reply, and
Skip. The TSVs stay the record: Skip sets that row's status to `skip` straight
away (Undo puts it back), so a thread you decide against doesn't come back.
After Skip the card offers a one-word reason, which goes in the row's notes.
Already replied sets the row `posted` (Undo again), for a thread you answered
some other way, so it leaves the page and counts toward the already-pitched check.
Drafts whose thread is more than the product's STALE_DAYS old are cleared as
`skip` on every load: by then the thread has moved on.

The page is served from 127.0.0.1, rebuilt on every load, and the server waits
for you to close the tab, since you reply from it and then expect the
record to know. On close it marks the Reddit drafts you answered (from your
comment feed), lists the Threads and X drafts still open, prints `closed` and exits,
so a session running it in the background is told when you're done. A reload
isn't a close. The page polls `/state` every few seconds, so drafts a pass writes after
it opened show up on their own, and a line at the top says what is still looking
(see looking.py). Threads has no feed to read without the API token, so those get
checked on your Threads account's Replies tab and marked with `leads threads-posted`.
"""
import html, http.server, json, re, subprocess, sys, tempfile, threading
from datetime import date

from . import looking, product, reddit, threadspage, tsv, x

PLATFORMS = ("Reddit", "Threads", "X")
SKIP_NOTE = "Skipped on the drafts page."
REPLIED_NOTE = "Marked replied on the drafts page."
# Offered after Skip and optional, so a pass can learn why replies weren't used.
SKIP_REASONS = ("Weak reply", "Wrong thread", "Old thread", "Not now")
# Or your own words, kept to one line so the notes cell stays readable.
REASON_LIMIT = 300


def clean_reason(reason):
    """A preset or your own reason as one line, or None when there's nothing usable."""
    if not isinstance(reason, str):
        return None
    reason = " ".join(reason.split()).rstrip(".")
    return reason if 0 < len(reason) <= REASON_LIMIT else None
# Threads counts the links too, so a draft that reads short can still be over.
THREADS_LIMIT = 500


def source(p, platform):
    return p.tsv_for(platform)


def days_old(r):
    """Age of the thread: `posted` is when it was posted, `found` when we saw it. The older wins."""
    days = []
    for key in ("posted", "found"):
        try:
            days.append((date.today() - date.fromisoformat(r.get(key) or "")).days)
        except ValueError:
            pass
    return max(days, default=0)


def handle(author):
    return (author or "").strip().lower().removeprefix("@").removeprefix("u/")


def pitched(products):
    """(platform, author) for everyone already sent a reply, from any product's TSVs.
    You answer from one account per platform, so a second pitch to the same
    person reads as spam whichever app it's for."""
    seen = set()
    for p in products:
        for platform in PLATFORMS:
            for r in tsv.read(source(p, platform))[1]:
                if tsv.status(r) == "posted" and handle(r.get("author")):
                    seen.add((platform, handle(r.get("author"))))
    return seen


def warnings(r, already):
    out = []
    if r["platform"] == "Threads" and len(r["reply_text"]) > THREADS_LIMIT:
        out.append(f"{len(r['reply_text'])} characters, over Threads' {THREADS_LIMIT}.")
    if r["platform"] == "X" and x.length(r["reply_text"]) > x.LIMIT:
        out.append(f"{x.length(r['reply_text'])} characters (links count 23), over X's {x.LIMIT}.")
    if (r["platform"], handle(r.get("author"))) in already:
        out.append(f"Already replied to @{handle(r.get('author'))} before.")
    return out


def load(products, pitched_from=None):
    already = pitched(pitched_from or products)
    out = []
    for p in products:
        for platform in PLATFORMS:
            for r in tsv.read(source(p, platform))[1]:
                reply = (r.get("reply") or "").strip()
                if not reply or tsv.status(r) not in tsv.OPEN:
                    continue
                # Drafts are stored wrapped in quotes so the TSV reads as speech.
                if len(reply) > 1 and reply[0] == reply[-1] == '"':
                    reply = reply[1:-1].strip()
                # A Threads row has no sub; THREADS_WHERE names a column of the product's own to show instead.
                where = r.get("subreddit") and f"r/{r['subreddit']}" or (r.get(p.get("THREADS_WHERE") or "") or "")
                row = {**r, "product": p.name, "app": p.title, "platform": platform,
                       "where": where, "reply_text": reply}
                row["warnings"] = warnings(row, already)
                out.append(row)
    # Newest first within each priority: an older thread is the likelier one to skip.
    out.sort(key=lambda r: r.get("posted") or r.get("found") or "", reverse=True)
    out.sort(key=lambda r: r.get("priority") or "9")
    return out


def expire(p):
    """Clear drafts whose thread is past STALE_DAYS. A post of our own (a submit URL) never expires."""
    stale = p.get("STALE_DAYS", 3)

    def update(r):
        if tsv.status(r) not in tsv.OPEN or not (r.get("reply") or "").strip():
            return False
        if r["url"].rstrip("/").endswith("/submit") or days_old(r) <= stale:
            return False
        r["status"] = "skip"
        r["notes"] = f"Cleared {date.today()}: thread over {stale} days old, not posted. {r.get('notes') or ''}".strip()
        return True
    for platform in PLATFORMS:
        for r in tsv.rewrite(source(p, platform), update):
            print(f"cleared (old): {p.title}: {r.get('title') or r['url']}", file=sys.stderr)


# A row's status before Skip, so Undo restores draft or new rather than guessing.
before_skip = {}


def set_skipped(p, platform, url, skip):
    key = (p.name, platform, url)

    def update(r):
        if r["url"] != url:
            return False
        notes = (r.get("notes") or "").strip()
        if skip and tsv.status(r) in tsv.OPEN:
            before_skip[key] = tsv.status(r)
            r["status"] = "skip"
            r["notes"] = f"{notes} {SKIP_NOTE}".strip()
            return True
        if not skip and tsv.status(r) == "skip" and key in before_skip:
            r["status"] = before_skip.pop(key)
            r["notes"] = notes.partition(SKIP_NOTE)[0].strip()
            return True
        return False
    return tsv.rewrite(source(p, platform), update)


# A row's status before Already replied, so Undo restores it.
before_replied = {}


def set_replied(p, platform, url, replied):
    key = (p.name, platform, url)

    def update(r):
        if r["url"] != url:
            return False
        notes = (r.get("notes") or "").strip()
        if replied and tsv.status(r) in tsv.OPEN:
            before_replied[key] = tsv.status(r)
            r["status"] = "posted"
            r["notes"] = f"{notes} {REPLIED_NOTE}".strip()
            return True
        if not replied and tsv.status(r) == "posted" and key in before_replied:
            r["status"] = before_replied.pop(key)
            r["notes"] = notes.partition(REPLIED_NOTE)[0].strip()
            return True
        return False
    return tsv.rewrite(source(p, platform), update)


def set_skip_reason(p, platform, url, reason):
    def update(r):
        notes = r.get("notes") or ""
        if r["url"] != url or tsv.status(r) != "skip" or SKIP_NOTE not in notes:
            return False
        r["notes"] = f"{notes.partition(SKIP_NOTE)[0]}{SKIP_NOTE} Reason: {reason}."
        return True
    return tsv.rewrite(source(p, platform), update)


def age(r):
    days = days_old(r)
    return "today" if days == 0 else "1 day old" if days == 1 else f"{days} days old"


MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def rich(text):
    """The reply as HTML with its Markdown links as anchors, or None when it has
    none. Pasting the Markdown into Reddit's rich-text box left the brackets in."""
    if not MD_LINK.search(text or ""):
        return None
    def para(p):
        out, at = [], 0
        for m in MD_LINK.finditer(p):
            out += [html.escape(p[at:m.start()]), f'<a href="{html.escape(m[2])}">{html.escape(m[1])}</a>']
            at = m.end()
        return "<p>" + ("".join(out) + html.escape(p[at:])).replace("\n", "<br>") + "</p>"
    return "".join(para(p) for p in re.split(r"\n\s*\n", text.strip()))


def key(r):
    return f"{r['product']}|{r['platform']}|{r['url']}"


def card(r, apps):
    e = lambda s: html.escape(s or "")
    title = r.get("title") or r.get("author") and f"@{r['author']}" or r["url"]
    # An app-thread reply is the pitch itself, so the card says which kind it is.
    kind = (r.get("kind") or "").strip() == "app" and "app thread"
    meta = " · ".join(x for x in [len(apps) > 1 and r["app"], kind, r["platform"], r["where"], age(r), r.get("engagement"),
                                  r.get("priority") and f"priority {r['priority']}"] if x)
    rich_html = rich(r["reply_text"])
    rich_attr = f' data-html="{e(rich_html)}"' if rich_html else ""
    # Leads the API found carry the post id a reply needs; Chrome-found ones get Copy only.
    post_reply = ('<button type="button" class="post-reply">Post reply</button>'
                  if r["platform"] == "Threads" and r.get("id") else "")
    reasons = '<span class="why">Why? ' + "".join(
        f'<button type="button" class="reason">{e(x)}</button>' for x in SKIP_REASONS) + (
        f'<form class="own"><input name="reason" maxlength="{REASON_LIMIT}" placeholder="Or your own reason">'
        '<button type="submit">Save</button></form></span>')
    return f"""<article data-product="{e(r['product'])}" data-platform="{e(r['platform'])}" data-url="{e(r['url'])}">
  <header><a href="{e(r['url'])}" target="_blank" rel="noopener">{e(title)}</a><span class="meta">{e(meta)}</span></header>
  {"".join(f'<p class="warn">{e(w)}</p>' for w in r.get("warnings", []))}
  <p class="notes">{e(r.get('notes'))}</p>
  <pre class="reply"{rich_attr}>{e(r['reply_text'])}</pre>
  <div class="actions">{post_reply}<button type="button" class="copy">Copy reply</button><button type="button" class="replied">Already replied</button><button type="button" class="skip">Skip</button>{reasons}</div>
</article>"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#e3e1dc; --accent:#0a7d5a; --warn:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161616; --card:#212121; --ink:#ececec; --muted:#9a9a9f; --line:#333; --accent:#3ec48f; --warn:#ff8a80; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, system-ui, sans-serif; }}
main {{ max-width:760px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 24px; }}
article {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin-bottom:16px; }}
header a {{ color:var(--ink); font-weight:600; font-size:16px; text-decoration:none; }}
header a:hover {{ color:var(--accent); text-decoration:underline; }}
.meta {{ display:block; color:var(--muted); font-size:13px; margin-top:2px; }}
.notes {{ color:var(--muted); font-size:13.5px; margin:10px 0; }}
.notes a {{ color:var(--accent); }}
.warn {{ color:var(--warn); font-weight:600; font-size:13.5px; margin:10px 0 0; }}
.reply {{ white-space:pre-wrap; font:inherit; background:var(--bg); border-radius:8px; padding:12px 14px; margin:0 0 12px; }}
button {{ font:inherit; font-size:14px; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:7px; padding:6px 14px; cursor:pointer; }}
button.done {{ color:var(--accent); border-color:var(--accent); }}
.actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
article.skipped > :not(header):not(.actions) {{ display:none; }}
article.skipped {{ opacity:.6; }}
article.skipped .copy, article.skipped .post-reply, article.skipped .replied {{ display:none; }}
article.replied > :not(header):not(.actions) {{ display:none; }}
article.replied {{ opacity:.6; }}
article.replied .copy, article.replied .post-reply, article.replied .skip {{ display:none; }}
.why {{ display:none; align-items:center; gap:6px; flex-wrap:wrap; color:var(--muted); font-size:13.5px; }}
article.skipped .why {{ display:flex; }}
button.reason {{ font-size:13px; padding:3px 10px; }}
form.own {{ display:flex; gap:6px; flex-basis:100%; max-width:480px; margin:0; }}
form.own input {{ flex:1; min-width:0; font:inherit; font-size:13px; padding:3px 8px; border:1px solid var(--line); border-radius:7px; background:var(--bg); color:var(--ink); }}
form.own button {{ font-size:13px; padding:3px 10px; }}
button.post-reply {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
article.posted {{ opacity:.6; }}
nav a {{ color:var(--accent); }}
.looking {{ display:flex; align-items:center; gap:10px; color:var(--muted); font-size:14px; margin:0 0 20px;
  padding:12px 16px; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
.looking[hidden] {{ display:none; }}
.spin {{ width:14px; height:14px; flex:none; border:2px solid var(--line); border-top-color:var(--accent);
  border-radius:50%; animation:spin .9s linear infinite; }}
.looking.done .spin {{ display:none; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
@media (prefers-reduced-motion: reduce) {{ .spin {{ animation-duration:3s; }} }}
.newtag {{ color:var(--accent); font-size:12px; font-weight:600; margin-left:8px; }}
</style></head><body><main>
<h1>{title}</h1>
<p class="sub"><span id="count">{count}</span> waiting · generated {today} · {footer}</p>
{nav}
<p id="looking" class="looking"{looking_hidden}><span class="spin" aria-hidden="true"></span><span class="what">{looking}</span></p>
<section id="cards">
{cards}
</section>
</main>
<script>
const live = location.protocol.startsWith("http");
const cards = document.getElementById("cards");
const cardKey = a => a.dataset.product + "|" + a.dataset.platform + "|" + a.dataset.url;
const lead = card => JSON.stringify({{ product: card.dataset.product, platform: card.dataset.platform, url: card.dataset.url }});
// The saved file has no server to write the TSV.
function fit(root) {{ if (!live) for (const b of root.querySelectorAll("button.skip, button.replied, button.post-reply")) b.remove(); }}
fit(document);
async function copy(b, card) {{
  const reply = card.querySelector(".reply"), text = reply.textContent, rich = reply.dataset.html;
  try {{
    // Both flavours: a rich-text box takes the links, a Markdown box the text.
    if (rich) await navigator.clipboard.write([new ClipboardItem({{
      "text/html": new Blob([rich], {{ type: "text/html" }}),
      "text/plain": new Blob([text], {{ type: "text/plain" }}) }})]);
    else await navigator.clipboard.writeText(text);
  }}
  catch {{  // file:// pages are not always a secure context
    const t = document.createElement("textarea"); t.value = text; document.body.append(t);
    t.select(); document.execCommand("copy"); t.remove();
  }}
  b.textContent = "Copied"; b.classList.add("done");
}}
async function toggle(b, card, cls, on, off, label, doneLabel) {{
  const undo = card.classList.contains(cls);
  b.disabled = true;
  const res = await fetch(undo ? off : on, {{ method: "POST", body: lead(card) }}).catch(() => null);
  b.disabled = false;
  if (!res || !res.ok) {{ b.textContent = "Couldn't save, try again"; return; }}
  card.classList.toggle(cls, !undo);
  b.textContent = undo ? label : doneLabel;
}}
async function saveReason(card, reason) {{
  const res = await fetch("/skip-reason", {{ method: "POST",
    body: JSON.stringify({{ ...JSON.parse(lead(card)), reason }}) }}).catch(() => null);
  return !!(res && res.ok);
}}
// Post reply asks on the card, then posts through the API on the second press.
async function postReply(b, card) {{
  if (!b.dataset.armed) {{ b.dataset.armed = 1; b.textContent = "Post to " + card.querySelector("header a").textContent; return; }}
  delete b.dataset.armed; b.disabled = true; b.textContent = "Posting…";
  const res = await fetch("/threads-reply", {{ method: "POST",
    body: JSON.stringify({{ product: card.dataset.product, url: card.dataset.url }}) }}).catch(() => null);
  const out = res ? await res.json().catch(() => ({{}})) : {{ error: "no answer from leads" }};
  if (!res || !res.ok) {{ b.disabled = false; b.textContent = "Post reply"; card.querySelector(".notes").textContent = out.error; return; }}
  card.classList.add("posted"); b.remove();
  card.querySelector(".notes").innerHTML = `Posted: <a href="${{out.permalink}}" target="_blank" rel="noopener">${{out.permalink}}</a>`;
}}
// One listener for every card, so cards that arrive later work the same.
document.addEventListener("click", async ev => {{
  const b = ev.target.closest("button"), card = b && b.closest("article");
  if (!card || b.closest("form.own")) return;
  if (b.classList.contains("copy")) return copy(b, card);
  if (b.classList.contains("post-reply")) return postReply(b, card);
  if (b.classList.contains("skip")) {{
    await toggle(b, card, "skipped", "/skip", "/unskip", "Skip", "Skipped · Undo");
    for (const x of card.querySelectorAll("button.reason, form.own button")) x.classList.remove("done");
    return;
  }}
  if (b.classList.contains("replied")) return toggle(b, card, "replied", "/replied", "/unreplied", "Already replied", "Marked replied · Undo");
  if (b.classList.contains("reason")) {{
    if (!await saveReason(card, b.textContent)) return;
    for (const x of card.querySelectorAll("button.reason")) x.classList.toggle("done", x === b);
    const own = card.querySelector("form.own button"); own.textContent = "Save"; own.classList.remove("done");
  }}
}});
document.addEventListener("input", ev => {{
  const f = ev.target.closest("form.own");
  if (f) {{ const b = f.querySelector("button"); b.textContent = "Save"; b.classList.remove("done"); }}
}});
document.addEventListener("submit", async ev => {{
  const f = ev.target.closest("form.own");
  if (!f) return;
  ev.preventDefault();
  const input = f.querySelector("input"), b = f.querySelector("button"), card = f.closest("article");
  if (!input.value.trim()) return;
  if (!await saveReason(card, input.value)) {{ b.textContent = "Couldn't save"; return; }}
  for (const x of card.querySelectorAll("button.reason")) x.classList.remove("done");
  b.textContent = "Saved"; b.classList.add("done");
}});
// New drafts arrive while a pass is still looking. They go in at their place in the
// order, marked New, and nothing already on the page moves or loses its state.
const lookingLine = document.getElementById("looking");
let wasLooking = !lookingLine.hidden;
function apply(s) {{
  const have = new Map([...cards.querySelectorAll("article")].map(a => [cardKey(a), a]));
  let prev = null;
  for (const [k, html] of s.cards) {{
    let a = have.get(k);
    if (!a) {{
      const t = document.createElement("template"); t.innerHTML = html.trim(); a = t.content.firstElementChild;
      a.classList.add("new");
      a.querySelector("header a").insertAdjacentHTML("afterend", '<span class="newtag">New</span>');
      fit(a);
      if (prev) prev.after(a); else cards.prepend(a);
      document.getElementById("empty")?.remove();
    }}
    prev = a;
  }}
  document.getElementById("count").textContent = s.count;
  const what = lookingLine.querySelector(".what");
  if (s.looking.length) {{
    lookingLine.hidden = false; lookingLine.classList.remove("done");
    what.textContent = "Still looking: " + s.looking.join(" · ") + ". New drafts appear here as they're written.";
    wasLooking = true;
  }} else if (wasLooking) {{
    lookingLine.classList.add("done");
    what.textContent = "Done looking.";
  }}
}}
async function poll() {{
  const res = await fetch("/state", {{ cache: "no-store" }}).catch(() => null);
  if (res && res.ok) apply(await res.json());
  setTimeout(poll, 3000);
}}
if (live) {{ setTimeout(poll, 3000); addEventListener("pagehide", () => navigator.sendBeacon("/closed")); }}
</script></body></html>
"""


def checked(rows, warned=None):
    """Print each draft's check: lines, once per draft and warning when `warned` is kept
    across calls, since the page polls every few seconds."""
    for r in rows:
        for w in r["warnings"]:
            if warned is not None:
                if (key(r), w) in warned:
                    continue
                warned.add((key(r), w))
            print(f"check: {r['app']} {r['platform']} {r['url']}: {w}", file=sys.stderr, flush=True)
    return rows


def looking_line(labels):
    return f"Still looking: {' · '.join(labels)}. New drafts appear here as they're written." if labels else ""


def render(products, live=True, warned=None):
    for p in products:
        expire(p)
    rows = checked(load(products, pitched_from=product.everything()), warned)
    apps = [p.title for p in products]
    footer = "closing this tab updates what's been replied to" if live else "open with `leads drafts` to skip"
    nav = '<p class="sub"><nav><a href="/threads">Threads page</a></nav></p>' if live else ""
    labels = looking.current(products, titled=len(products) > 1) if live else []
    empty = '<p id="empty">Nothing yet.</p>' if labels else '<p id="empty">Nothing waiting.</p>'
    page = PAGE.format(title=f"{' + '.join(apps)} reply drafts", count=len(rows), today=date.today().isoformat(),
                       footer=footer, nav=nav, looking=html.escape(looking_line(labels)),
                       looking_hidden="" if labels else " hidden",
                       cards="\n".join(card(r, apps) for r in rows) or empty)
    return rows, page


def state(products, warned=None):
    """What the open page polls for: every open draft as [key, card HTML] in page
    order, the count, and what is still looking. No expiry here; that runs on load."""
    rows = checked(load(products, pitched_from=product.everything()), warned)
    apps = [p.title for p in products]
    return {"cards": [[key(r), card(r, apps)] for r in rows], "count": len(rows),
            "looking": looking.current(products, titled=len(products) > 1)}


# A reload fires the close beacon and then loads again at once; wait this long
# for that load before treating the beacon as the tab closing.
RELOAD_GRACE = 3.0
EDITS = ("/skip", "/unskip", "/skip-reason", "/replied", "/unreplied")


def serve(products, open_browser=True, keep=False, port=0, page="drafts"):
    """Serve the page until the tab closes, then sync. With keep, sync on every close and keep serving.
    page="threads" opens the Threads page instead; both are served either way."""
    by_name = {p.name: p for p in products}
    closed = threading.Event()
    live = {"pending": None}
    warned = set()

    def on_close():
        live["pending"] = None
        sync(products)
        print("closed", flush=True)
        if not keep:
            closed.set()

    class Handler(http.server.BaseHTTPRequestHandler):
        def threads_route(self, method):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
            out = live["threads"].handle(method, self.path, body)
            if out is None:
                return False
            status, headers, data = out
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

        def do_GET(self):
            if live["pending"]:
                live["pending"].cancel()  # a reload, not a close
                live["pending"] = None
            if self.threads_route("GET"):
                return
            if self.path == "/state":
                body, kind = json.dumps(state(products, warned)).encode(), "application/json"
            else:
                body, kind = render(products, warned=warned)[1].encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path not in EDITS + ("/closed",) and self.threads_route("POST"):
                return
            if self.path in EDITS:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    lead = json.loads(body)
                    p = by_name[lead["product"]]
                    if lead["platform"] not in PLATFORMS:
                        raise KeyError(lead["platform"])
                    # Only a row that's on the page (or was skipped from it) can change.
                    if self.path == "/skip-reason":
                        reason = clean_reason(lead["reason"])
                        if not reason:
                            raise KeyError(lead["reason"])
                        changed = set_skip_reason(p, lead["platform"], lead["url"], reason)
                    elif self.path in ("/replied", "/unreplied"):
                        changed = set_replied(p, lead["platform"], lead["url"], self.path == "/replied")
                    else:
                        changed = set_skipped(p, lead["platform"], lead["url"], self.path == "/skip")
                    if not changed:
                        raise KeyError(lead["url"])
                except (ValueError, KeyError, TypeError):
                    self.send_response(400)
                    self.end_headers()
                    return
            self.send_response(204)
            self.end_headers()
            if self.path == "/closed":
                live["pending"] = threading.Timer(RELOAD_GRACE, on_close)
                live["pending"].start()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    live["threads"] = threadspage.Page(products, server.server_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/" + ("threads" if page == "threads" else "")
    if open_browser:
        # Always Chrome, whatever the default browser is: the Threads and X steps run in Chrome.
        subprocess.run(["open", "-a", "Google Chrome", url])
    print(f"open at {url}; waiting for the tab to close", flush=True)
    # A day's cap so a forgotten tab doesn't leave the server up for good.
    if not closed.wait(timeout=24 * 3600):
        print("tab never closed; syncing anyway", flush=True)
        sync(products)
    server.shutdown()
    server.server_close()
    return server


def sync(products):
    """After you close the tab: mark answered Reddit drafts, list Threads and X ones still open."""
    for p in products:
        # Two requests, so a short pause is enough.
        reddit.mark_posted(p, pause=2)
    for r in load(products):
        if r["platform"] in ("Threads", "X"):
            print(f"{r['platform'].lower()} open: {r['app']}: @{r.get('author')} {r['url']}", flush=True)


def write_file(products):
    rows, page = render(products, live=False)
    out = __import__("pathlib").Path(tempfile.gettempdir()) / f"{'-'.join(p.name for p in products)}-reply-drafts.html"
    out.write_text(page)
    print(f"{len(rows)} draft(s): {out}")
    return out
