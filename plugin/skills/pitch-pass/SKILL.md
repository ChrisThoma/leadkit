---
name: pitch-pass
description: Run a pitch pass for one of your apps - follow up on pitches already sent, pitch the next roundup authors, app-list curators and creators, find new targets, and record what each listing produced. Use when the user says "pitch pass", "who should we pitch", "follow up on the pitches", or "find roundups/lists/creators for <app>". Not a leads pass (replying to threads); that's leads-pass.
---

# Pitch pass

Someone else's audience (a roundup, an app list, a creator) often sells more than
a hundred replies in threads. A pitch pass works that list.

Targets live in `$LEADKIT_DATA/products/<name>/pitches.tsv` (default
`~/leadkit-data`), one row per page the app should end up on. `leads pitches`
reads them. Never edit the TSV by hand.

    leads pitches                    # follow-ups due, awaiting a reply, next to pitch
    leads pitches add URL target="Site (Author)" kind=roundup route=... fit=...
    leads pitches set URL status=sent code=ABC123     # fills today and a follow-up in 7 days
    leads pitches set URL status=listed result="listed; N page views, N units"

Kinds: roundup, list, creator, directory, press. Statuses: todo, drafted, sent,
followed-up, listed, declined, no-reply, skip.

## Steps

1. **Run `leads pitches`.** Work in the order it prints: follow-ups due, then the
   next targets. A pass is the due follow-ups plus two new pitches. A pitch that
   reads like a batch gets ignored.
2. **Follow-ups due.** One nudge per pitch, a week after it was sent, two or three
   sentences with one new thing to say (a release, a rating count, a feature the
   author's readers asked for). Replace a promo code that has expired. Then
   `status=followed-up`. When that comes due again with no answer,
   `status=no-reply` and leave them alone.
3. **Check each target before drafting.** It has to be live, updated in the last
   year or so, list apps like this one, and have a way in (a form, an email, a
   submission link). If not, `status=skip` with the reason in `notes`. Read what
   the author asks of developers and what they wrote about the nearest competitor.
4. **Check the app is ready for that author.**
   `curl -s "https://itunes.apple.com/lookup?id=<app id>&country=us"` gives the live
   rating count. Press waits until the app has ratings worth showing. Each pitch
   gets its own campaign link (`ct=<target>`) and, if the user has them, a promo
   code. If there are none left, ask once and draft the rest meanwhile.
5. **Draft.** A few plain sentences: what the app does for that author's readers,
   where it would sit on their page, what it does that the listed apps don't, and
   a plain ask, signed with the user's name. Check every claim (features, price,
   platforms) against the code and the live store listing that day. Then
   `status=drafted`.
6. **The user approves and sends** every pitch themselves. Once they say it went,
   `leads pitches set URL status=sent code=...`.
7. **Find new targets** when fewer than five `todo` rows are left:
   - Whoever lists the app's competitors (`aso top "<keyword>"` names them; search
     "best <category> apps", "<competitor> alternatives").
   - App lists built around a device or OS feature.
   - Creators who cover the subject, where the app fits a video they'd make anyway.
   - Newsletters and blogs that take submissions.
   Skip competitors' own pages and affiliate lists. Write `fit` as the one reason
   this author would care.
8. **Read back what a listing did.** When a pitch lands, `status=listed` with the
   listing's URL in `result`. A week later add what it sent (App Analytics
   referrers, `asc-sales --days 14`, against the app's usual days). A listing that
   sold nothing is a result too.

End with one short summary: what was nudged, what's waiting on the user, what was
added, and any listing's numbers.
