"""Proofer (a made-up app for this example): a sourdough timer that tracks a
starter's feedings and tells you when the dough is ready to shape.

Copy this folder to $LEADKIT_DATA/products/<your app>/ (or start from
`leads setup --new <name>`), then change every block to fit your app.
"""

NAME = "Proofer"
# The app's own repo. `leads` and `aso` pick the product from the folder you run them in.
REPO = "~/Development/proofer"
LEADS_DIR = "leads"
# Drafts older than this many days are cleared as skip: the thread has moved on.
STALE_DAYS = 4

# Reddit
USER_AGENT = "proofer-watch/0.1 (by u/your_reddit_name)"
# Seconds between requests when reading Reddit's own feeds.
PAUSE = 35.0

# Answer subs: people ask questions here, and a reply answers first.
SUBREDDITS = ["Sourdough", "Breadit", "Baking", "AskBaking"]
# Subs whose rules you haven't read yet. Leads from them say so.
RULES_UNCHECKED = {"Baking", "AskBaking"}
# Subs never to reply in (no self-promotion at all, for instance), lowercase.
EXCLUDED = {"bread"}
# Subs small enough to read every new post of, as well as searching them.
NEW_FEEDS = ["Sourdough"]
# Each runs once over all SUBREDDITS as one multireddit, through Arctic Shift.
SEARCHES = [
    "app OR apps",
    "starter OR levain",
    '"bulk ferment" OR "bulk fermentation" OR proofing OR "proof time"',
    '"feeding schedule" OR "when to feed"',
]
# Extra subs with their own searches: app subs, searched for your topic only.
GROUPS = [{"name": "apps", "subreddits": ["iosapps", "apps"], "searches": ["sourdough OR bread OR baking"]}]

# Weighted regexes scored against title and body; a lead has to reach MIN_SCORE.
SIGNALS = {
    r"\bfeeding schedule\b|\bwhen (should|do) i feed\b": 5,
    r"\b(bulk|final) (ferment(ation)?|proof(ing)?)\b": 3,
    r"\bover ?proof(ed)?\b|\bunder ?proof(ed)?\b": 4,
    r"\b(keep|keeping) track\b|\bforget (to feed|my starter)\b": 4,
    r"\b(any|good|best) (apps?|timers?|tools)\b|\bwhich app\b": 4,
    r"\bstarter\b|\blevain\b": 1,
    r"\bsourdough\b": 1,
}
# Sales, gear and other people's launches: anywhere a reply would read as an ad.
NEGATIVE = {
    r"\bfor sale\b|\bgiveaway\b": -10,
    r"\bdutch oven\b|\bbanneton\b|\bmixer\b": -2,
    r"\bmy (app|site)\b|\bi (made|built) an? (\w+ ){0,3}app\b": -8,
}
MIN_SCORE = 5
# (gate, table): a table counts only when its gate regex matches. None always counts.
SCORE_TABLES = [(None, SIGNALS), (None, NEGATIVE)]

# Ad subs: you post an ad of your own here (`leads posts`). Keys in leadkit/posts.py.
POST_SUBS = {
    "apps": {"rules": "Say you made it."},
    "iosapps": {"flair": "a price flair", "every_days": 30, "per_account": True,
                "rules": "Read the sidebar's account-age and karma rules first."},
}

# Threads, searched in Chrome (`leads threads-searches`):
# {"group": [(query, TOP or RECENT, is_community, optional tag_id), ...]}
TOP, RECENT = "", "&filter=recent"
THREADS_SEARCHES = {
    "keywords": [
        ("sourdough starter", RECENT, False),
        ("sourdough app", TOP, False),
        ("bread proofing", TOP, False),
    ],
}
# A file in the app's repo to attach to showcase replies, or None.
THREADS_MEDIA = None

# App Store keywords (`aso`). It takes part once APP_STORE_ID and ASO_KEYWORDS are set.
# APP_STORE_ID = 1234567890
ASO_KEYWORDS = ["sourdough", "sourdough timer", "starter tracker", "bread proofing"]
# What `aso locales` tells claude -p when it drafts seed phrases in other languages.
ASO_ABOUT = ("Proofer is an iPhone app for sourdough bakers: it tracks a starter's feedings "
             "and times bulk fermentation and proofing.")
# Words to keep out of keyword fields, with why.
ASO_AVOID = {"recipe": "recipe collections (the app has no recipes)"}
# Name to App Store ID, for the "ahead of us" column.
ASO_COMPETITORS = {}
