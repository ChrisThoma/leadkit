"""App Store analytics for every app: impressions, product page views and downloads per day.

Apple's Analytics Reports API hands out each day's numbers as a file, one per report and
processing date. An ONGOING request keeps only about the last 21 daily files, and a
ONE_TIME_SNAPSHOT request holds the 30 days before it was made. So `leads analytics sync`
saves every file it hasn't seen to `marketing/analytics-raw/` (committed: once Apple drops
a file, this copy is the only one) and `rows()` sums them into one table.

Two reports are kept:
- "App Store Discovery and Engagement Standard": impressions and product page views, by
  source (search, browse, web referrer, app referrer...) and territory.
- "App Downloads Standard": first-time downloads and redownloads (updates and restores
  are dropped), by the same source and territory.

A daily file holds late rows for earlier dates as well as its own day. Snapshot rows win
for dates the snapshot covers; ongoing rows count after the snapshot's last date.
"""
import gzip, json, subprocess, urllib.request
from collections import defaultdict
from pathlib import Path

from . import product

RAW = product.DATA / "marketing" / "analytics-raw"
REPORTS = {
    "discovery": "App Store Discovery and Engagement Standard",
    "downloads": "App Downloads Standard",
}
DOWNLOAD_TYPES = {"First-time download": "downloads", "Redownload": "redownloads"}
EVENTS = {"Impression": "impressions", "Page view": "page_views"}
METRICS = ("impressions", "page_views", "downloads", "redownloads")


def asc_get(path, query=(), run=subprocess.run):
    cmd = ["asc", "api", "GET", path, "--paginate"]
    for q in query:
        cmd += ["--query", q]
    out = run(cmd, capture_output=True, text=True, timeout=300)
    if out.returncode:
        raise RuntimeError(f"asc api GET {path}: {(out.stderr or out.stdout).strip()[:300]}")
    return json.loads(out.stdout or "{}").get("data", [])


def apps(run=subprocess.run):
    """[(app_id, store title)] for every app on the account."""
    out = run(["asc", "apps", "list", "--paginate", "--output", "json"],
              capture_output=True, text=True, timeout=120)
    data = json.loads(out.stdout)
    return [(a["id"], a["attributes"]["name"]) for a in data.get("data", data)]


def requests(app_id, get=asc_get):
    """{"ONGOING": id, "ONE_TIME_SNAPSHOT": id} for the requests this app has."""
    found = {}
    for r in get(f"/v1/apps/{app_id}/analyticsReportRequests"):
        if not r["attributes"].get("stoppedDueToInactivity"):
            found.setdefault(r["attributes"]["accessType"], r["id"])
    return found


def create_request(app_id, access, run=subprocess.run):
    body = {"data": {"type": "analyticsReportRequests", "attributes": {"accessType": access},
                     "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}
    run(["asc", "api", "POST", "/v1/analyticsReportRequests", "--confirm", "--body", json.dumps(body)],
        capture_output=True, text=True, timeout=120, check=True)


def raw_path(app_id, kind, access, day):
    tag = "snapshot" if access == "ONE_TIME_SNAPSHOT" else "ongoing"
    return RAW / app_id / kind / f"{tag}-{day}.tsv.gz"


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return gzip.decompress(r.read()).decode()


def join_segments(texts):
    """Segments of one instance as one TSV: the first header, every segment's rows."""
    lines = []
    for t in texts:
        rows = t.splitlines()
        if not rows:
            continue
        lines += rows if not lines else rows[1:]
    return "\n".join(lines) + "\n"


def sync_app(app_id, get=asc_get, download=fetch, log=print):
    """Save every daily file for this app not already in RAW. Returns how many were new."""
    reqs = requests(app_id, get)
    new = 0
    for access, req in reqs.items():
        for kind, name in REPORTS.items():
            reports = get(f"/v1/analyticsReportRequests/{req}/reports", [f"filter[name]={name}"])
            for rep in reports:
                for inst in get(f"/v1/analyticsReports/{rep['id']}/instances", ["filter[granularity]=DAILY"]):
                    day = inst["attributes"]["processingDate"]
                    path = raw_path(app_id, kind, access, day)
                    if path.exists():
                        continue
                    segs = get(f"/v1/analyticsReportInstances/{inst['id']}/segments")
                    text = join_segments(download(s["attributes"]["url"]) for s in segs)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(gzip.compress(text.encode(), mtime=0))
                    new += 1
    return new, reqs


def sync(log=print, get=asc_get, download=fetch, app_list=None, create=create_request):
    total = 0
    for app_id, title in (app_list or apps()):
        reqs = requests(app_id, get)
        if "ONGOING" not in reqs:
            create(app_id, "ONGOING")
            log(f"{title}: asked Apple for ongoing reports (first files arrive in a day or two)")
        n, _ = sync_app(app_id, get, download, log)
        total += n
        if n:
            log(f"{title}: {n} new file(s)")
    log(f"{total} new file(s) in {RAW.relative_to(product.DATA)}")
    return total


def parse(text, kind):
    """(date, metric, source, territory, counts, unique) rows from one raw file."""
    lines = text.splitlines()
    if not lines:
        return
    head = lines[0].split("\t")
    col = {h: i for i, h in enumerate(head)}
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) < len(head):
            continue
        if kind == "discovery":
            metric = EVENTS.get(f[col["Event"]])
        else:
            metric = DOWNLOAD_TYPES.get(f[col["Download Type"]])
        if not metric:
            continue
        counts = int(f[col["Counts"]] or 0)
        unique = int(f[col["Unique Counts"]] or 0) if "Unique Counts" in col else counts
        yield f[col["Date"]], metric, f[col["Source Type"]], f[col["Territory"]], counts, unique


def rows(app_id, raw=None):
    """{(date, metric, source, territory): [counts, unique]} for one app, all files summed."""
    base = (raw or RAW) / app_id
    out = defaultdict(lambda: [0, 0])
    for kind in REPORTS:
        # A file restates the three days before its processing date, so each date's rows
        # come from the newest file that has that date (ties: ongoing over snapshot).
        by_date = {}
        files = sorted((base / kind).glob("*.tsv.gz"), key=lambda f: (processed(f), f.name.startswith("ongoing-")))
        for f in files:
            per = defaultdict(list)
            for r in parse(gzip.decompress(f.read_bytes()).decode(), kind):
                per[r[0]].append(r)
            by_date.update(per)
        for day_rows in by_date.values():
            for d, metric, src, terr, c, u in day_rows:
                v = out[(d, metric, src, terr)]
                v[0] += c
                v[1] += u
    return out


def processed(f):
    """The processing date in a raw file's name (snapshot-2026-10-30.tsv.gz)."""
    return f.name.split("-", 1)[1].removesuffix(".tsv.gz")


# ---- the daily job and the page's Sync button ---------------------------------
import os, plistlib, sys, threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LABEL = "local.leadkit.analytics"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "leadkit-analytics.log"


LAST_SYNC = product.DATA / "marketing" / ".last-sync.json"  # local, never committed


def mark_synced(path=LAST_SYNC, now=None):
    """Record that a full sync finished, for the dashboard's "Last synced"."""
    now = now or datetime.now(timezone.utc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}))


def last_sync(path=LAST_SYNC):
    """When the last full sync finished (UTC ISO), or "" if none is on record."""
    try:
        return json.loads(path.read_text()).get("at", "")
    except (OSError, ValueError, AttributeError):
        return ""


def sync_everything(log=print):
    """Apple's analytics files, then sales and posts (`leads log sync`): what the
    dashboard's Sync button and the 3 a.m. job both run."""
    from . import mlog
    sync(log=log)
    log("Sales and posts (leads log sync)...")
    for line in mlog.sync(14):
        log(line)
    from . import ratings
    log("Ratings (App Store and Google Play)...")
    for e in ratings.fetch(apps(), play=ratings.play_ratings).get("errors", []):
        log("  " + e)
    mark_synced()


def scheduled(day=None):
    """What the daily job runs: sync everything, commit what changed (no push)."""
    from . import aso_cli, mlog
    sync_everything()
    day = day or datetime.now().date().isoformat()
    aso_cli.commit_ranks(product.DATA, [RAW, mlog.SALES, mlog.POSTS, mlog.DIR / "ratings.json"], day, message=f"analytics: daily sync {day}")


def job_plist(hour, minute, home, python, log):
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "leadkit.cli", "analytics", "sync", "--scheduled"],
        "EnvironmentVariables": {"PYTHONPATH": str(home), "LEADKIT_DATA": str(product.DATA),
                                 "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + str(Path.home() / ".local/bin")},
        "WorkingDirectory": str(home),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
    })


def install_job(at="03:00", off=False):
    """The Mac's clock is America/New_York, so 03:00 is 3 a.m. Eastern. A Mac asleep at
    3 runs the job when it wakes."""
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST)], capture_output=True)
    if off:
        PLIST.unlink(missing_ok=True)
        return f"removed {PLIST}"
    hour, minute = (int(x) for x in at.split(":"))
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(job_plist(hour, minute, product.HOME, sys.executable, LOG))
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST)], check=True)
    return f"daily analytics sync at {at}: {PLIST}\nlog: {LOG}"


class Job:
    """One sync at a time, run in a thread, its lines kept for the page to show."""

    def __init__(self, work=sync_everything):
        self.work, self.lines, self.running, self.error, self.finished = work, [], False, None, None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.running:
                return False
            self.lines, self.running, self.error = [], True, None
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self):
        try:
            self.work(log=self.lines.append)
        except Exception as e:  # noqa: BLE001  shown on the page
            self.error = str(e)[:300]
        finally:
            self.running, self.finished = False, datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M %p %Z")

    def state(self):
        return {"running": self.running, "lines": self.lines[-8:], "error": self.error, "finished": self.finished}
