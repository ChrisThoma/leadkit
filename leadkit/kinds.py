"""Lead kinds. Every lead is one of two:

- domain: someone asking about the app's own subject (sourdough timing for
  a baking app). Each product's config owns these
  searches and score tables. The reply answers the question first, then pitches.
- app: a thread inviting any app ("show off your app", "what are you
  building"). Shared here by every product, so a new app gets them and a fix
  reaches all of them. The asker wants links, so the reply is the pitch: what
  the app is, a link, media where the place allows it. These threads move fast,
  so only ones under about a day old count.

Leads are split this way because a pass can find nothing pitchable in a
day's topic subs while the showcase threads still take a reply. The `kind` column in each leads TSV is what
says, after a few weeks, which kind is worth the time (`leads kinds`).
"""
from . import tsv

DOMAIN, APP_KIND = "domain", "app"
TOP, RECENT = "", "&filter=recent"

APP = {
    # Threads, searched in Chrome. The replies that get views go in within a few
    # hours. "Promote your product" threads are left out: replies there are
    # buried among dozens of link drops and draw no clicks.
    "threads": {
        "showcase": [
            ("show off your app", TOP, False),
            ("show me your app", TOP, False),
            ("indie devs show me your app", TOP, False),
            ("who's building an app", TOP, False),
            ("what are you building", TOP, False),
            ("what are you working on", TOP, False),
            ("launching an app", TOP, False),
            ("drop your app", TOP, False),
        ],
    },
    # Reddit: one site-wide search for posts inviting apps. Every sub it finds
    # is unchecked by default, so each lead says to read the sub's
    # self-promotion rules before the first reply there.
    "site_searches": [
        '"show off your app" OR "share your app" OR "drop your app" OR "what are you building" OR "self promotion thread"',
    ],
    # Reddit: the show-your-work subs, searched together as one multireddit
    # for their weekly "what are you building" threads. A weekly
    # thread keeps drawing readers for days, so these keep leads up to
    # showcase_max_hours instead of a day. Rules for these subs weren't
    # readable from a script on 2026-11-10 (403); each lead says to check.
    "subreddits": ["buildinpublic", "SideProject", "indiehackers", "IndieDev", "iOSProgramming",
                   "alphaandbetausers", "AppBusiness"],
    "searches": [
        'weekly OR thread OR "share your" OR "what are you building" OR "what are you working on" '
        'OR "show off" OR "drop your" OR "promote your"',
    ],
    "showcase_max_hours": 72,
    "max_hours": 24,
    "min_score": 5,
    "score_tables": [(None, {
        r"\b(show( off| me)?|share|drop|post|plug|link) (your|ur) (apps?|projects?|side ?projects?|products?|startups?)\b": 5,
        r"\bwhat are you (building|working on|making|shipping)\b|\bwho'?s building\b": 5,
        r"\bself[- ]?promo(tion)? (thread|saturday|sunday|day|megathread)\b|\bweekly (showcase|promo)\b": 5,
        r"\bshare (what|something) (you'?re|you are) (building|working on|making)\b|\b(share|show|promote|drop) your (work|wins?|progress|launch(es)?)\b": 5,
        r"\bweekly\b.{0,20}\b(thread|showcase|share|promo)\b|\b(showcase|feedback|promo|share) (saturday|sunday|friday|monday)\b": 3,
        r"\bindie (devs?|developers?|makers?|hackers?)\b": 1,
        # Someone else's launch or a tool for launches: a reply there reads as
        # a competing ad.
        r"\bi('?ve| have)? (just )?(made|built|launched|created|released|shipped) an? (\w+ ){0,3}(app|tool|site|platform|directory)\b": -8,
        r"\bwould you use\b|\bfeedback on my\b|\bmy (app|startup|saas|product)\b": -8,
        r"\bhiring\b|\bfor hire\b|\bcofounder\b": -8,
    })],
}


def enabled(p):
    return p.get("APP_LEADS", True)


def of(r):
    """A row's kind. Rows from before 2026-11-03 have none and were all domain."""
    return (r.get("kind") or "").strip() or DOMAIN


def tally(rows):
    """{kind: {status: count}}, for judging which kind earns its time."""
    out = {}
    for r in rows:
        status = tsv.status(r) or "new"
        counts = out.setdefault(of(r), {})
        counts[status] = counts.get(status, 0) + 1
    return out


def report(p):
    for name, path in (("Reddit", p.reddit_tsv), ("Threads", p.threads_tsv), ("X", p.x_tsv)):
        _, rows = tsv.read(path)
        for kind, counts in sorted(tally(rows).items()):
            print(f"{p.title} {name} {kind}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
