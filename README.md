# leadkit

leadkit is the marketing toolkit I use for my own iOS and Android apps. It finds
Reddit, Threads and X posts where someone is asking for what your app does, keeps
your reply drafts in one place, tracks App Store keyword ranks every day, and puts
your store analytics and your posts on one timeline so you can see what moved the
numbers.

It runs from the terminal, and most of the daily work runs through the Claude Code
skills in `plugin/`. A Claude session runs the searches, reads the threads and
drafts the replies. You read every draft and post it yourself. Nothing in leadkit
posts on its own.

What's in it:

- Leads: Reddit, Threads and X searches scored against a table you write for each
  app, with one TSV of drafts per platform and a local drafts page that records
  what you posted.
- Study: which posts by other people do well in your app's communities, and what
  they have in common.
- Pitches: a follow-up list of roundup authors, app lists and creators to pitch.
- App Store keywords (`aso`): daily ranks, keyword research, and keyword fields
  for all 40 App Store languages.
- Dashboard: App Store and Google Play impressions, page views, downloads and
  sales on one local page, with your posts marked on the timeline.

## Contents

- [Requirements](#requirements)
- [Getting started](#getting-started)
- [How it's split](#how-its-split)
- [How to use it](#how-to-use-it)
- [Commands](#commands)
- [Reddit](#reddit)
- [Threads](#threads)
- [Tests](#tests)
- [Contributing](#contributing)

## Requirements

- macOS. Scheduled jobs use launchd and banners use macOS notifications.
- Python 3.9 or newer. No packages to install.
- [Claude Code](https://claude.com/claude-code) for the skills, and
  [Claude in Chrome](https://claude.com/chrome) for the Threads and X steps.

Everything else is optional and listed under [Optional pieces](#optional-pieces).

## Getting started

    git clone https://github.com/ChrisThoma/leadkit.git ~/Development/leadkit
    ~/Development/leadkit/bin/setup

`bin/setup` goes step by step and asks before each change:

1. Makes your data folder, `~/leadkit-data` (set `LEADKIT_DATA` to put it
   somewhere else), and copies `settings.example.py` there as `settings.py`. All
   your data lives there, apart from the code, so `git pull` never touches it.
2. Links `leads`, `aso`, `asc-sales` and `play-sales` into `~/.local/bin`.
3. Installs the daily keyword-rank job in launchd.
4. Reports what each product still needs.

Then add your first app:

1. Fill in your accounts in `~/leadkit-data/settings.py`.
2. Run `leads setup --new myapp`. It asks for the app's name, its repo and its
   App Store ID, and writes `products/myapp/config.py` and `cases.py` in the data
   folder. [`examples/products/proofer/`](examples/products/proofer/) is a
   filled-in config for a made-up sourdough app, to copy from.
3. Fill in the config: subreddits, searches, the score table that says what a
   lead looks like, Threads searches and keywords. Put example post titles in
   `cases.py` (titles that should be leads, and near misses that shouldn't) and
   run `bin/test`, which checks them against your score table.
4. Try it: `leads -p myapp reddit --dry-run` prints what it would find without
   saving anything.
5. Optional but recommended: `git init` the data folder so the daily jobs commit
   ranks and leads there. Keep that repo private. The leads files name real
   people and hold your drafted replies.

A product config is plain Python data. A trimmed piece of the example:

```python
NAME = "Proofer"
REPO = "~/Development/proofer"

# Answer subs: people ask questions here, and a reply answers first.
SUBREDDITS = ["Sourdough", "Breadit", "Baking", "AskBaking"]
# Subs never to reply in (no self-promotion at all, for instance), lowercase.
EXCLUDED = {"bread"}
# Subs small enough to read every new post of, as well as searching them.
NEW_FEEDS = ["Sourdough"]
```

### The Claude Code skills

The `plugin/` folder holds four skills: `leads-pass`, `study`, `pitch-pass` and
`leadkit` (keywords and setup). Add them in Claude Code with:

    /plugin marketplace add ~/Development/leadkit
    /plugin install leadkit@leadkit

Then say "leads pass for myapp" or "/study myapp" in a session. The Threads and X
steps use Claude in Chrome, signed in to your accounts.

### Optional pieces

- The `claude` CLI. `aso locales` uses `claude -p` to draft keyword seeds in other
  languages, `leads study` uses it to label hooks, and `leads comments` uses it for
  the hourly reply triage.
- [`asc`](https://asccli.sh) (`brew install asc`) for the App Store analytics, the
  dashboard and `aso export --asc`.
- `asc-sales` reads daily App Store units and proceeds by app. It needs an App
  Store Connect API key in `~/.config/asc-sales/config.json`
  (`bin/asc-sales --help`).
- `play-sales` reads daily Google Play sales from the Play Console's reports
  bucket with a service account (`bin/play-sales --help`).
- The Threads API. `leads threads-api` searches Threads by keyword, which needs
  your own Meta app with the Threads use case and Meta's approval of
  `threads_keyword_search`. Without it, the Chrome searches do the same job.
- The X API. `leads x-insights` reads your X posts' views. It's pay-per-use: put
  an app's Bearer Token from console.x.com in `~/.config/leadkit/x_bearer_token`.
- [`terminal-notifier`](https://github.com/julienXX/terminal-notifier)
  (Homebrew) for clickable banners from the hourly comment watcher. Without it
  you get plain macOS banners.

## How it's split

- `leadkit/` is the engine, shared by every product.
- `$LEADKIT_DATA/settings.py` holds your accounts, shared by every product.
- `$LEADKIT_DATA/products/<name>/config.py` holds what's unique to one app:
  subreddits, searches, score tables and their gates, the score bar, Threads
  searches and media, keywords. Plain data, plus a hook function only where data
  can't express something.
- `$LEADKIT_DATA/products/<name>/cases.py` holds that app's lead and not-lead
  examples. `bin/test` checks every product's cases, so a change to the engine
  can't quietly break one app's scoring.
- `$LEADKIT_DATA/products/<name>/leads/` holds the TSVs: `reddit-leads.tsv`,
  `threads-leads.tsv`, `x-leads.tsv`.
- `$LEADKIT_DATA/marketing/` holds the sales log, the posts log and saved App
  Store analytics.
- `leadkit/kinds.py` is the shared app kind of lead: threads inviting any app
  ("what are you building", showcase threads), with their own score table and a
  one-day age limit. Everything a product's config finds is the domain kind.
  `leads kinds` counts each kind's drafts, posts and skips. A product turns the
  shared kind off with `APP_LEADS = False`.

## How to use it

### Finding people to reply to

A Claude session runs this as a leads pass (the `leads-pass` skill): `leads
reddit`, the Threads searches in Chrome, drafts logged in the product's TSVs with
`leads set`, then `leads drafts` opens the page you copy replies from. Close the
tab when you're done and it records what you posted.

### What does well (`leads study`)

The other direction from a leads pass: across the product's subs and Threads
searches, which posts by other people got the most votes, replies and likes, and
what those have in common. Run it before planning a post or a new format.

- `leads study reddit` reads the last 30 days of every sub in the config through
  Arctic Shift, ranks each sub's top tenth on its own, and compares them with the
  rest: format, kind of post, length, day and hour, and what happened to people
  showing their own app.
- On Threads, a session opens each of `leads study threads-urls` (Top tab) in one
  Chrome tab and runs `leads study threads-js` there. `leads study threads-receive`
  saves what it gathered and writes the report.
- Both then have `claude -p` name the hook of the top posts and of as many random
  others, so the report says which hooks win more often than they turn up.
  `--no-label` skips that.

Reports land in `products/<name>/study/`.

### Pitches (`leads pitches`)

`products/<name>/pitches.tsv` lists roundups, app lists, creators and press to
pitch. `leads pitches` says which follow-ups are due and who to pitch next.
`leads pitches set URL status=sent` starts a 7-day follow-up clock.

### X

`leads x-post [threads-url]` turns your latest Threads post into X posts: split at
paragraphs within X's 280 characters (a link counts 23), with `ct=x` campaign
codes, and the video saved for upload. `leads x-searches` gives a leads pass its X
searches to open in Chrome.

### App Store analytics (`leads dashboard`)

One local page with line charts of impressions, product page views, first-time
downloads, units sold and proceeds, for all apps together and for each app, with
each post from `marketing/posts.tsv` marked on the timeline, and star ratings from
both stores. `leads dashboard` serves it on 127.0.0.1:8418 and opens Chrome. The
Live · 24h view reads App Store Connect's hourly Trends through `asc web auth
login`. Sync runs `leads analytics sync`, and `leads analytics daily` installs a 3 a.m. launchd job that does the
same. The page says when the code is newer than the running server, and Restart
loads it.

### The marketing log (`leads log`)

`leads log sync` pulls 14 days of units from `asc-sales` and `play-sales` into
`marketing/sales.tsv`, and collects your posts into `marketing/posts.tsv`. `leads
log week` prints units against the week before and every post that has been out
two days with no numbers. `leads log day` prints one day's sales and posts as JSON.

### App Store keywords (`aso`)

1. Ranks, every day. A launchd job runs `aso check --all` and appends to each
   product's `aso/ranks.tsv`. `aso report` shows the last check, with the rank at
   the check before in brackets.
2. Choosing English keywords. `aso suggest <word>` lists what Apple
   autocompletes, and `aso top "<phrase>"` shows who holds a phrase and how many
   ratings they have. Phrases you keep go in `ASO_KEYWORDS`.
3. The other 39 languages. `aso locales` writes a keyword field for every App
   Store language to `aso/locales.md` (about 35 minutes). `aso locales --review`
   checks every word against Wiktionary. `aso export --todo` prints each field to
   paste into App Store Connect, and `aso export --pasted <locale>` records it.

## Commands

Inside an app's repo the product is picked from the repo. Elsewhere, pass
`-p <name>` before or after the subcommand. `leads --help` and `aso --help` list
everything.

    leads reddit                     # mark posted, then find new Reddit leads
    leads reddit --dry-run           # print leads and near misses, append nothing
    leads thread URL [URL ...]       # read a Reddit thread and its comments
    leads reddit-eval -v             # score every post you've already judged
    leads set URL status=skip notes+="why"   # change one leads row
    leads threads-searches [group]   # Threads search URLs to open in Chrome
    leads threads-searches --js      # extractor to run on a results page
    leads threads-posted [URL ...]   # mark Threads rows posted
    leads threads-yield              # views of your replies by the search that found the lead
    leads drafts                     # the drafts page; exits when the tab closes
    leads looking "reading threads"  # tell the drafts page what's still running
    leads kinds                      # drafts, posts and skips per lead kind
    leads stats                      # found, drafted, posted by sub and week
    leads posts                      # ad subs: your own posts' scores, when each takes the next ad
    leads comments                   # the hourly watcher: find, triage with claude, banner the drafts
    leads study reddit               # what does well in the product's subs
    leads log day                    # one day's sales and posts as JSON
    leads pitches                    # follow-ups due and who to pitch next
    leads dashboard                  # the analytics page
    leads setup [--check] [--new NAME]

    aso check [--all]                # rank every keyword and save it
    aso report [-c de]               # the last saved check, no network
    aso top "phrase"                 # who holds a keyword, with rating counts
    aso suggest word                 # Apple's typing suggestions
    aso daily [--at 09:15] [--off]   # install or remove the daily check
    aso locales [--only de-DE ja]    # a keyword field for every App Store language
    aso locales --review             # look every field word up on Wiktionary
    aso export [--todo]              # each field, to paste into App Store Connect
    aso export --asc 1.5 --dir D     # every language's listing as an `asc metadata` folder

## Reddit

Reddit refuses anonymous search, and its public feeds allow about one read every
30 to 40 seconds. So posts and threads come from
[Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md),
a free public Reddit archive with new posts within minutes and comments within the
hour. A run lists every post in each sub back to the cutoff and runs your searches
locally. A sub it can't list is read from Reddit's own feed, and
`--source reddit` reads only Reddit. Please go easy on Arctic Shift. It's run by
volunteers.

A run:

1. Marks posted every queued row you've since commented on (from the comment feed
   of `REDDIT_REPLY_ACCOUNT` in settings), or posted to its sub.
2. Reads each `NEW_FEEDS` sub's new posts, and runs each search over all
   `SUBREDDITS` and each group's subs.
3. Scores title and body against `SCORE_TABLES`. A `(gate, table)` pair counts
   only when its gate matches.
4. Appends what clears `MIN_SCORE` as `new`, and prints near misses without
   appending them. Many of the best leads come from the near misses.

Read each sub's rules before replying there. `RULES_UNCHECKED` in a product's
config marks subs you haven't checked yet, and leads from them say so.

## Threads

Without an API token, a pass runs `leads threads-searches` in Chrome and reads each
page with the `--js` extractor. When posting, type the prose and paste the store
link, because a typed URL only links part of it. Mark replies with
`leads threads-posted`, fed by `--replies-js` on your account's Replies tab.

`leads threads-api` uses Meta's keyword search instead. It needs a Meta app with
the "Access the Threads API" use case, `threads_basic` and
`threads_keyword_search`, its Threads app ID in `THREADS_APP_ID`, an https page you
control as `THREADS_REDIRECT`, and the app secret in
`~/.config/leadkit/threads_app_secret`. Run `leads threads-login` to sign in and
save a token. Until Meta approves keyword search in App Review, it only finds your
own posts.

## Tests

    bin/test

The tests run against the made-up products in `tests/fixtures`, never your data
folder, and nothing reaches the network.

## Contributing

Issues and pull requests are welcome. Run `bin/test` before sending a change, and
add a case to a fixture product when you change how leads are scored. Keep real
leads, usernames and sales figures out of issues and the repo.

## License

MIT, see [`LICENSE`](LICENSE).
