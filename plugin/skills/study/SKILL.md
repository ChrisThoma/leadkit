---
name: study
description: Audience research for one of your apps on Reddit and Threads - what other people post that does well in the app's communities, read in full, turned into what it means for the app. Use when the user says /study <app>, "study reddit/threads for <app>", or "what does well for <app>". Not a leads pass (finding posts to reply to); that's leads-pass.
---

# /study <app>: what does well on Reddit and Threads

Arguments: the app (a leadkit product name: `ls $LEADKIT_DATA/products`, default
`~/leadkit-data/products`). "reddit" or "threads" alone limits it to that half.

Before starting, say in one sentence what runs and how long: "Reddit study of
<app>'s N subs (about 10 minutes in the background) and a Threads Top-tab study in
Chrome (about 15 minutes)."

## 1. Reddit (background)

`leads study reddit -p <app>` reads 30 days of every sub in the product's config
through Arctic Shift, then labels hooks with `claude -p`. Run it in the background
with its log in a temp file. It writes `products/<app>/study/reddit-<date>.md`. Do
the Threads half while it runs.

When it's done, check the report's sub table against the log: a sub with 0 posts or
a handful (dead or misnamed) is a finding to report, not a gap to hide.

## 2. Threads (Chrome, while Reddit runs)

1. `leads study threads-urls -p <app>` lists the Top-tab search URLs.
2. Open ONE new tab. For each URL: navigate, wait for results, then run the output
   of `leads study threads-js` with `await` in front. It gathers into that tab's
   sessionStorage, so every search must run in the same tab.
3. Start `leads study threads-receive -p <app>` in the background. It prints a
   localhost URL and a dump script, then waits up to 15 minutes. Run the script in
   the same tab. It saves the posts, appends to `study/threads.tsv` and writes
   `study/threads-<date>.md`.

If Chrome or Threads won't cooperate after 2-3 tries, stop and say so; finish the
Reddit half.

## 3. Read the winners in full

Tables say what wins, not why. From each report's "Read these in full" list:

- Reddit: `leads -p <app> thread <url> ...` on all ten.
- Threads: open the top posts in the Chrome tab and read the post and top replies.

For each, note what the title promises, what the body opens with, what the
comments answer to, and whether the poster replied. For image posts the picture
isn't in the text, so the comments are the evidence. Don't describe an image you
haven't seen.

## 4. Write it into the reports

Add a section above "Read these in full" in each report:
`## What the ten read in full have in common (read <date>)`, grouped by kind of
post with scores, then `**What this means for <app>**`.

The "means for" part has to hold up:
- Check every claim about the app against the product's config, `ASO_ABOUT` and
  the app's listing. No features it doesn't have.
- Say plainly where the app can't be named (sub rules, megathreads) and where a
  post would only work from someone who really did the thing.
- Prices only from the live store listing that day.

## 5. Finish

- If the study run printed something misleading, fix the tool test-first in
  `leadkit/study.py` and `tests/test_study.py`.
- Commit the study files in the data folder if it's a git repo.
- Close the Chrome tab you opened.
- Report briefly: what wins on each platform (with numbers), what the posts read in
  full share, and what it means for the app.
