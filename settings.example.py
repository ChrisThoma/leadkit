"""Your accounts, shared by every product. `leads setup` copies this file to
~/leadkit-data/settings.py (or $LEADKIT_DATA/settings.py); edit that copy."""

# Your Reddit accounts, so your own posts never come back as leads.
REDDIT_OWN_ACCOUNTS = {"your_reddit_name"}
# The account you post replies from. Reading its comment feed is how a draft
# becomes `posted` without anyone editing the TSV by hand.
REDDIT_REPLY_ACCOUNT = "your_reddit_name"

# The X account that posts for your apps (optional: only `leads x-*` uses it).
X_ACCOUNT = "your_x_handle"
# The Threads account that posts for your apps.
THREADS_ACCOUNT = "your_threads_handle"
# Threads API (optional; the Chrome searches work without it). Create a Meta app
# with the Threads use case and put its Threads app ID here, not the Meta app ID.
# Sign-in sends the browser to THREADS_REDIRECT with ?code=...; any https page
# you control that shows the address works, then `leads threads-login '<address>'`.
THREADS_APP_ID = ""
THREADS_REDIRECT = "https://example.com/threads/callback/"

# Sent with Reddit and App Store requests. Reddit asks for a contact in it.
CONTACT = "u/your_reddit_name"

# A Markdown file of your writing rules (optional). Ask for a change on the drafts
# page gives it to the Claude that redrafts the reply.
VOICE_GUIDE = ""

# App Store storefronts `aso check --all` ranks for every app besides the US, each in
# its own language's phrases. An app skips one whose language isn't recorded in its
# aso/pasted.tsv. A product's own ASO_COUNTRIES replaces this list.
ASO_COUNTRIES = []
