"""The Threads page, served next to the drafts page from 127.0.0.1.

It is where every Threads API feature has a button: sign in, search public
posts, read mentions, add either as a lead, publish a post, and look over our
recent posts and replies with their insights, the replies people left, and
Delete. The drafts page's Post reply button lands here too. Every button that
publishes or deletes asks a second time on the page itself (no browser
dialogs, which stall Claude in Chrome).

Sign-in: /threads-signin sends Chrome to Threads with state "<port>.<nonce>".
Threads redirects to the site's /threads/callback/ page, which forwards the
code to /threads-callback here; the nonce must match before any code is used.
"""
import html, json, secrets
from urllib.parse import parse_qs, urlparse

from . import threads, threadsapi, tsv
from .product import settings

JSON = {"Content-Type": "application/json"}


class Page:
    def __init__(self, products, port, token=None):
        self.by_name = {p.name: p for p in products}
        self.products = products
        self.port = port
        self.nonce = secrets.token_urlsafe(16)
        self._token = token or (lambda: threads.token_file(products[0]).read_text().strip())

    def token(self):
        return self._token()

    def handle(self, method, path, body=b""):
        """(status, headers, bytes) for one request, or None when it isn't ours."""
        url = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            data = json.loads(body) if body else {}
            route = ROUTES.get((method, url.path))
            if not route:
                return None
            return route(self, q, data)
        except (ValueError, KeyError, TypeError) as e:
            return self.json({"error": str(e)}, 400)
        except threadsapi.ApiError as e:
            return self.json({"error": f"Threads said {e}"}, 502)

    def json(self, obj, status=200):
        return status, JSON, json.dumps(obj).encode()

    # Pages and sign-in.

    def page(self, q, data):
        return 200, {"Content-Type": "text/html; charset=utf-8"}, render(self.products).encode()

    def signin(self, q, data):
        return 302, {"Location": threads.authorize_url(f"{self.port}.{self.nonce}")}, b""

    def callback(self, q, data):
        if q.get("state") != f"{self.port}.{self.nonce}":
            raise ValueError("sign-in state doesn't match this page; start again from Sign in")
        saved = threads.exchange(threads.login_code(q["code"]))
        threads.save_token(self.products[0], saved)
        return 302, {"Location": "/threads"}, b""

    # Reading.

    def account(self, q, data):
        try:
            return self.json(threadsapi.me(self.token()))
        except (OSError, threadsapi.ApiError):
            return self.json({"username": None})

    def search(self, q, data):
        return self.json({"posts": threadsapi.search(self.token(), q["q"].strip())})

    def mentions(self, q, data):
        return self.json({"posts": threadsapi.mentions(self.token())})

    def ours(self, q, data):
        """Our recent posts and replies, each with insights and the replies people left."""
        tok, out = self.token(), []
        posts = threadsapi.own_posts(tok, 5) + threadsapi.call(
            "me/replies", tok, {"limit": 5, "fields": threadsapi.POST_FIELDS}).get("data", [])
        for p in posts:
            out.append(p | {"insights": threadsapi.insights(tok, p["id"]),
                            "answers": threadsapi.replies(tok, p["id"], settings.THREADS_ACCOUNT)})
        out.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
        return self.json({"posts": out})

    # Acting.

    def add_lead(self, q, data):
        row = threads.add_lead(self.by_name[data["product"]], data["post"], data.get("how", "threads page"))
        return self.json({"added": bool(row)})

    def reply(self, q, data):
        return self.json(threads.reply_to_lead(self.by_name[data["product"]], data["url"], self.token()))

    def publish(self, q, data):
        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("nothing to publish")
        return self.json(threadsapi.publish(self.token(), text))

    def delete(self, q, data):
        media_id = str(data["id"])
        threadsapi.delete(self.token(), media_id)
        # If it was a reply to a lead, the lead's row says so.
        for p in self.products:
            def update(r):
                if r.get("reply_id") != media_id:
                    return False
                r["status"], r["reply_id"] = "deleted", ""
                r["notes"] = f"Reply deleted on the Threads page. {r.get('notes') or ''}".strip()
                return True
            tsv.rewrite(p.threads_tsv, update)
        return self.json({"deleted": media_id})


ROUTES = {
    ("GET", "/threads"): Page.page,
    ("GET", "/threads-signin"): Page.signin,
    ("GET", "/threads-callback"): Page.callback,
    ("GET", "/api/account"): Page.account,
    ("GET", "/api/search"): Page.search,
    ("GET", "/api/mentions"): Page.mentions,
    ("GET", "/api/ours"): Page.ours,
    ("POST", "/api/add-lead"): Page.add_lead,
    ("POST", "/threads-reply"): Page.reply,
    ("POST", "/api/publish"): Page.publish,
    ("POST", "/api/delete"): Page.delete,
}


def render(products):
    options = "".join(f'<option value="{html.escape(p.name)}">{html.escape(p.title)}</option>' for p in products)
    return PAGE.replace("{{options}}", options).replace("{{account}}", html.escape(settings.THREADS_ACCOUNT))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Threads · leads</title>
<style>
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#e3e1dc; --accent:#0a7d5a; --warn:#b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg:#161616; --card:#212121; --ink:#ececec; --muted:#9a9a9f; --line:#333; --accent:#3ec48f; --warn:#ff8a80; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, system-ui, sans-serif; }
main { max-width:760px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:0 0 10px; }
.sub, .meta, .empty { color:var(--muted); } .meta { font-size:13px; }
section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin-bottom:16px; }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
input, textarea, select { font:inherit; border:1px solid var(--line); background:var(--bg); color:var(--ink); border-radius:7px; padding:6px 10px; }
input[type=search] { flex:1; min-width:180px; } textarea { width:100%; box-sizing:border-box; min-height:70px; }
button, .button { font:inherit; font-size:14px; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:7px; padding:6px 14px; cursor:pointer; text-decoration:none; }
button.primary, .button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
button.danger { color:var(--warn); border-color:var(--warn); }
.item { border-top:1px solid var(--line); padding:10px 0; } .item:first-of-type { border-top:0; }
.item p { margin:4px 0 8px; white-space:pre-wrap; } .item a { color:var(--ink); font-weight:600; }
.answers { margin:6px 0 8px 14px; padding-left:10px; border-left:2px solid var(--line); font-size:14px; }
.status { font-size:13.5px; margin-top:8px; } .status.err { color:var(--warn); }
.status a { color:var(--accent); }
nav a { color:var(--accent); }
</style></head><body><main>
<h1>Threads</h1>
<p class="sub" id="account">Checking the connected account…</p>
<p class="sub"><nav><a href="/">Reply drafts</a></nav></p>

<section id="search-box">
  <h2>Search public posts</h2>
  <form class="row" id="search-form"><input type="search" id="q" placeholder="sourdough, bread timer, …" required>
  <button class="primary">Search</button></form>
  <div class="row" style="margin-top:8px"><span class="meta">Add leads to</span><select id="product">{{options}}</select></div>
  <div id="search-results"></div>
</section>

<section>
  <h2>Mentions of @{{account}}</h2>
  <button id="load-mentions">Load mentions</button>
  <div id="mention-results"></div>
</section>

<section>
  <h2>New post</h2>
  <textarea id="post-text" placeholder="What's new?"></textarea>
  <div class="row"><button class="primary" id="publish">Publish…</button></div>
  <div class="status" id="publish-status"></div>
</section>

<section>
  <h2>Our recent posts and replies</h2>
  <button id="load-ours">Load posts, views and replies</button>
  <div id="our-posts"></div>
</section>
</main>
<script>
const esc = s => (s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", body: JSON.stringify(body) } : {});
  const out = await res.json().catch(() => ({ error: "no answer from leads" }));
  if (!res.ok) throw new Error(out.error || res.status);
  return out;
}
// Publish and Delete ask on the page, then act on the second press.
function twoStep(button, ask, act) {
  const label = button.textContent;
  button.addEventListener("click", async () => {
    if (!button.dataset.armed) { button.dataset.armed = 1; button.textContent = ask(); return; }
    delete button.dataset.armed; button.disabled = true;
    try { await act(); } finally { button.disabled = false; button.textContent = label; }
  });
}
function postItem(p, how) {
  const div = document.createElement("div"); div.className = "item";
  div.innerHTML = `<a href="${esc(p.permalink)}" target="_blank" rel="noopener">@${esc(p.username)}</a>
    <span class="meta">${esc((p.timestamp || "").slice(0, 10))}</span><p>${esc(p.text)}</p>
    <div class="row"><button class="add">Add as lead</button><span class="status"></span></div>`;
  div.querySelector(".add").addEventListener("click", async e => {
    const s = div.querySelector(".status");
    try { const out = await api("/api/add-lead", { product: document.getElementById("product").value, post: p, how });
          s.textContent = out.added ? "Added to the leads file." : "Already a lead, or our own post."; e.target.disabled = true; }
    catch (err) { s.textContent = err.message; s.classList.add("err"); }
  });
  return div;
}
function list(el, posts, how) {
  el.replaceChildren(...(posts.length ? posts.map(p => postItem(p, how)) : [Object.assign(document.createElement("p"), { className: "empty", textContent: "Nothing found." })]));
}
// Closing the tab ends `leads threads` the way it ends `leads drafts`; leaving
// for the Threads sign-in isn't a close.
let signingIn = false;
document.addEventListener("click", e => { if (e.target.closest('a[href="/threads-signin"]')) signingIn = true; });
addEventListener("pagehide", () => { if (!signingIn) navigator.sendBeacon("/closed"); });
api("/api/account").then(a => {
  document.getElementById("account").innerHTML = a.username
    ? `Signed in as <strong>@${esc(a.username)}</strong> · <a class="button" href="/threads-signin">Sign in again</a>`
    : `Not signed in · <a class="button primary" href="/threads-signin">Sign in with Threads</a>`;
});
document.getElementById("search-form").addEventListener("submit", async e => {
  e.preventDefault();
  const q = document.getElementById("q").value, el = document.getElementById("search-results");
  el.textContent = "Searching…";
  try { list(el, (await api("/api/search?q=" + encodeURIComponent(q))).posts, "search " + q); }
  catch (err) { el.textContent = err.message; }
});
document.getElementById("load-mentions").addEventListener("click", async () => {
  const el = document.getElementById("mention-results"); el.textContent = "Loading…";
  try { list(el, (await api("/api/mentions")).posts, "mention"); } catch (err) { el.textContent = err.message; }
});
twoStep(document.getElementById("publish"), () => "Publish as @{{account}}", async () => {
  const s = document.getElementById("publish-status"), text = document.getElementById("post-text").value;
  try { const out = await api("/api/publish", { text }); s.innerHTML = `Published: <a href="${esc(out.permalink)}" target="_blank">${esc(out.permalink)}</a>`; s.classList.remove("err"); document.getElementById("post-text").value = ""; }
  catch (err) { s.textContent = err.message; s.classList.add("err"); }
});
document.getElementById("load-ours").addEventListener("click", async () => {
  const el = document.getElementById("our-posts"); el.textContent = "Loading…";
  let posts; try { posts = (await api("/api/ours")).posts; } catch (err) { el.textContent = err.message; return; }
  el.replaceChildren(...posts.map(p => {
    const div = document.createElement("div"), m = p.insights || {}; div.className = "item";
    const answers = (p.answers || []).map(a => `<div>@${esc(a.username)}: ${esc(a.text)}</div>`).join("");
    div.innerHTML = `<a href="${esc(p.permalink)}" target="_blank" rel="noopener">${p.is_reply ? "Our reply" : "Our post"}</a>
      <span class="meta">${esc((p.timestamp || "").slice(0, 10))} · ${m.views ?? 0} views · ${m.likes ?? 0} likes · ${(p.answers || []).length} replies</span>
      <p>${esc(p.text)}</p>${answers ? `<div class="answers">${answers}</div>` : ""}
      <div class="row"><button class="danger">Delete…</button><span class="status"></span></div>`;
    twoStep(div.querySelector(".danger"), () => "Delete from Threads", async () => {
      try { await api("/api/delete", { id: p.id }); div.querySelector("p").textContent = "Deleted."; div.querySelector(".danger").remove(); }
      catch (err) { const s = div.querySelector(".status"); s.textContent = err.message; s.classList.add("err"); }
    });
    return div;
  }));
});
</script></body></html>
"""
