"""One reply that names every live app, kept ready to copy (`leads apps`).

For threads that invite all of them ("any Duo-optimized apps?", "show off your
app"), where a reply about one app would leave the others out. The text is in
all-apps.json in your data folder: one line per app and variant, plus the store
link patterns with your campaign code. Only list apps that are live. The page is
a plain file, so it can be bookmarked and needs no server.
"""
import html, json, subprocess
from datetime import date

from . import drafts, product

DATA = product.DATA / "all-apps.json"
OUT = product.DATA / "all-apps.html"


def app_store(data, app_id):
    return data["app_store"].format(id=app_id, code=data["code"])


def play_store(data, package):
    return data["play_store"].format(id=package, code=data["code"])


def reply(data, variant):
    """The variant's reply as Reddit Markdown, one short paragraph per app."""
    out = [variant["intro"]]
    for a in data["apps"]:
        text = a[variant["key"]].replace("{link}", f"[{a['name']}]({app_store(data, a['id'])})")
        if variant["play"] and a["play"]:
            text += f" Also on [Android]({play_store(data, a['play'])})."
        out.append(text)
    return "\n\n".join(out)


def render(data):
    e = html.escape
    cards = []
    for v in data["variants"]:
        md = reply(data, v)
        rich = drafts.rich(md)
        # Shown as it will look on Reddit; Copy carries the Markdown too.
        cards.append(f"""<article>
  <header><strong>{e(v['title'])}</strong><span class="meta">{e(v['when'])}</span></header>
  <div class="reply" data-md="{e(md)}">{rich}</div>
  <div class="actions"><button type="button" class="copy">Copy reply</button><button type="button" class="md">Copy as Markdown</button></div>
</article>""")
    style = drafts.PAGE[drafts.PAGE.index("<style>"):drafts.PAGE.index("</style>")].replace("{{", "{").replace("}}", "}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>All apps reply</title>
{style}
div.reply {{ white-space:normal; }} .reply p {{ margin:0 0 10px; }} .reply p:last-child {{ margin:0; }} .reply a {{ color:var(--accent); }}
header {{ margin-bottom:12px; }}
</style></head><body><main>
<h1>All apps reply</h1>
<p class="sub">{len(data['apps'])} live apps · made {date.today()} · edit all-apps.json, then run leads apps</p>
{"".join(cards)}
</main>
<script>
document.addEventListener("click", async ev => {{
  const b = ev.target.closest("button");
  if (!b) return;
  const r = b.closest("article").querySelector(".reply"), md = r.dataset.md;
  const item = {{ "text/plain": new Blob([md], {{ type: "text/plain" }}) }};
  if (b.className.startsWith("copy")) item["text/html"] = new Blob([r.innerHTML], {{ type: "text/html" }});
  const label = b.textContent;
  try {{ await navigator.clipboard.write([new ClipboardItem(item)]); b.textContent = "Copied"; b.classList.add("done"); }}
  catch {{ b.textContent = "Couldn't copy"; }}
  setTimeout(() => {{ b.textContent = label; b.classList.remove("done"); }}, 2000);
}});
</script></body></html>
"""


def run(open_browser=True):
    if not DATA.exists():
        print(f"No {DATA}. Copy examples/all-apps.json there and fill in your apps.")
        return 1
    OUT.write_text(render(json.loads(DATA.read_text())))
    if open_browser:
        subprocess.run(["open", "-a", "Google Chrome", str(OUT)])
    print(OUT)
