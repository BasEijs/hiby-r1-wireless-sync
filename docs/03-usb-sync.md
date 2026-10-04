# Coming from a USB sync

Before this project, the test unit was synced from a Mac over USB by an
rsync script that launchd started whenever the player was mounted. Copies are
in `reference/`, with personal paths replaced:

| File | Role |
|---|---|
| `reference/mp3sync.sh` | the rsync script |
| `reference/mp3sync.plist` | launchd agent, `StartOnMount` |
| `reference/mp3sync.2s.sh` | SwiftBar menu-bar progress indicator |

If you have something similar, read this page before your first wireless
sync.

## Do not run both against the same card

**[verified]** The two syncs fight each other. exFAT stores wall-clock time
with no timezone, and macOS and the player disagree about it
(`docs/09-flash-and-verify.md` §3). So every USB sync rewrote timestamps in
the macOS convention, and the *next* wireless sync saw the whole library as
changed — 93 GB on the test unit.

It was caught doing exactly that: the player was plugged in to receive a
firmware update, `StartOnMount` fired, and the USB sync started rewriting an
artist directory before it was stopped.

So: once the wireless sync works, **disable the USB auto-trigger.**

```
launchctl unload -w ~/Library/LaunchAgents/<your-agent>.plist
```

Keep the script if you like, as a rescue path. Running it by hand has the
same effect on timestamps, and the wireless side needs another repair pass
afterwards.

## What the USB script did — the behaviour to preserve

**Player layout:**
- `Music/` — full mirror, `rsync -rtv --modify-window=2 --delete`
- `Podcasts/` — selective, via `--files-from` (no `--delete`)
- `book/` — **never touched by anything**

**Podcast selection** (the union of three finds, `sort -u`):
1. everything modified in the last `MAX_DAYS=21` days
2. all `*.jpg` / `*.png` cover art
3. the newest `KEEP_MIN=2` episodes of every show, regardless of age

**Podcast deletion** — a separate pass, not rsync. For each show, everything
past the newest 2 was deleted *only if* also older than 21 days.

The wireless sync keeps all of this:

1. `book` untouched.
2. Music mirrored with deletes.
3. Podcasts: 21-day window, newest 2 per show always kept, cover art included.
4. Old episodes cleaned up (beyond newest 2 **and** older than 21 days).
5. Single-run locking.
6. Some form of progress/completion feedback.

How each is done over rsyncd, where there is no remote shell:
`server/mp3sync/README.md`.

## Why move the sync to the server at all

The first full USB sync took ~3 hours (~18 files/min), largely because the
data crossed the network **twice**: server → Mac over SMB, then Mac → player
over USB. The Mac owned none of the data. A server that holds the library
locally can send it once.
