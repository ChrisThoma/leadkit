---
name: leads-pass
description: Run a leads pass for one of your apps that has a leadkit product - find Reddit, Threads and X threads to reply to, draft replies, and open the drafts page. Use when the user says "leads pass", "marketing run", "find threads to reply to", "draft a reply to this post", or sends a thread link to answer for an app.
---

# Leads pass

A leads pass finds threads to reply to, drafts the replies, and opens the drafts
page the user posts from. It doesn't write posts, videos or a marketing plan.

The tools are `leads` (the leadkit repo, README "How to use it"). Inside an app's
repo the product is picked from the repo; elsewhere pass `-p <name>`. What's
unique to an app (subs, searches, score tables, media) is in
`$LEADKIT_DATA/products/<name>/config.py` (`~/leadkit-data` unless LEADKIT_DATA is
set). Read it, and any notes in the app's repo about its audience and which
communities dislike app mentions, before drafting.

Every lead is one of two kinds, recorded in the TSVs' `kind` column. **Domain**
leads ask about the app's own subject; each product's config finds them. **App**
leads are threads inviting any app ("show off your app", "what are you
building"); the shared searches in `leadkit/kinds.py` find them for every
product. `leads kinds` counts each kind's drafts, posts and skips, which says
after a few weeks whether app threads earn their time.

## Steps

0. **One pass per app at a time.** If another session is already running a pass
   for this app, don't start a second one: Reddit and Threads rate-limit you.
1. **Numbers first (optional).** If the user has `asc-sales` or `play-sales` set
   up, run `asc-sales --days 7` and `play-sales --days 7`. If one says its config is
   missing, say so in one line and go on. Then `aso report` if the product tracks
   keywords (the daily job already ran the check; don't run `aso check`). Name each
   keyword whose `store` rank moved, in one line, or nothing.
2. **Reddit.** `leads reddit` in the background (a few minutes). It marks the
   user's answered threads posted, then lists each sub through Arctic Shift (a
   public Reddit archive) and runs the config's searches locally. It appends new
   leads, each tagged with its kind. App leads are kept only under a day old, and
   their notes say to check the sub's self-promotion rules first.
   Read threads with `leads thread <url> [<url> ...]`. Once triage is done, commit
   the leads TSV in the data folder if it's a git repo, so a pass cut off later
   keeps its triage.
3. **Read the near misses thread by thread**, not by title. Posts up to about 5
   days old with few replies still count. Near misses read in full are where many
   of the best drafts come from.
4. **Threads.** Open the URLs from `leads threads-searches` in Claude in Chrome
   (Top tab unless the group says otherwise), and read each results page with the
   script from `leads threads-searches --js`. Its first line names the search
   (`# search: drop your app (top)`); that's the `query` for every lead from that
   tab. Run `leads threads-yield` first to see which searches have found threads
   worth replying to. Threads throttles after about ten quick searches. Take
   showcase threads only when they're under about a day old.
   **X** works the same way: `leads x-searches`, then `leads x-searches --js` in
   each tab. X rows go in `x-leads.tsv` through `leads set` with the x.com URL. X
   counts a link as 23 characters and allows 280 per post.
5. **Log every lead**, drafted or skipped, with a reason. A skip keeps the next
   pass from reading it again. Set `kind` on every row you add by hand, and on
   Threads and X rows set `query` to the search that found it (`query=sent` for a
   thread the user sent). Change a leads TSV only with `leads set`, one row per
   call:

       leads set URL status=skip notes+="gear question"
       leads set URL --add kind=domain query="sourdough starter" notes="..."
       printf '%s' "$reply" | leads set URL status=draft reply=-

   Never write a script that edits the file: replies span several lines and are
   quoted, and a hand edit can break every row after it.
6. **Draft.** An app-kind reply is the pitch itself: what the app is and who it's
   for in a sentence or two, the links, and media where the product has
   `THREADS_MEDIA`. A domain reply answers the question first, then ties a short
   pitch to the poster's own words, with a link where the community allows one.
   Give both store links (each with its campaign code) when the app is on both
   stores and the post isn't about one platform. Check every feature a draft names
   against the app's code or release notes. Write plainly, like a person in that
   community, not like an ad. The user approves every reply.
7. **Open the drafts page** as soon as the first draft is written, with
   `leads drafts` in the background, and keep drafting: the open page picks up
   later drafts on its own. While still working, say what with
   `leads looking "<a few words>"` (it lasts 20 minutes, so renew it), and run
   `leads looking --done` after the last draft. Fix or skip every draft the run
   prints a `check:` line for (a Threads draft over 500 characters, or someone
   already replied to). The user posts from the page's copy buttons; the run exits
   when they close the tab, after marking their Reddit replies. Then open the
   Threads account's Replies tab in Chrome, run `leads threads-searches --replies-js`,
   and pipe its pairs into `leads threads-posted`. For X drafts it lists as
   `x open:`, mark each answered one with `leads x-posted <thread-url> <reply-url>`.
8. **Commit** the leads TSVs in the data folder if it's a git repo. Leads files
   name real people: never put them in an app repo or anywhere public.

## Posting for the user

Only when they ask you to post, and only in Claude in Chrome on Threads or X:

- Type the prose, then paste the store link in one piece (a ClipboardEvent with a
  DataTransfer). A typed URL on Threads links only part of it. Check the link holds
  the whole URL before posting, and the posted link's href after.
- Links get a store campaign code (`ct=threads`, `ct=reddit`, `ct=x`; Play
  `&referrer=utm_source%3Dthreads`).
- To put a Threads post on X, run `leads x-post [threads-url]`: it prints the X
  parts (split at paragraphs within 280) and saves the post's video for upload.
- Media for showcase replies: `leads threads-searches --attach-js` stops the file
  picker, then upload the file it names to the reply dialog's file input.
- On Reddit the link goes on the app name as Markdown (`[App](url)`), never a bare
  URL. The user pastes Reddit replies themselves.
- No DMs unless they ask for that one.

## Changing the tools

Fix or extend the engine in the leadkit repo's `leadkit/`, not in an app repo. A
new search, sub or phrase goes in that product's `config.py`; a new example post
goes in its `cases.py`. Run `bin/test` in the leadkit repo before committing.
