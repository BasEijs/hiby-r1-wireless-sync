# mp3sync — the sync server

Syncs a music library and a podcast folder to the R1's rsync daemon over
WiFi, and serves a web UI showing what a sync would do. Needs the custom
firmware from `docs/07-firmware-build.md` on the player.

## Run it

```
cd server/mp3sync
cp .env.example .env        # PLAYER, MUSIC_DIR, PODCAST_DIR at minimum
docker compose up -d --build
docker logs -f mp3sync      # "listening on :8787, player <ip>:873"
```

Then open `http://<server>:8787/` and press **Preview**. Nothing is written
to the player until you press **Sync now** or the player asks.

**Before the first real sync:** if the card was filled by another tool, the
preview may show your whole library as changed. That is the exFAT timestamp
problem — do the one-time repair in `docs/09-flash-and-verify.md` §3 first.

Dry run from the command line:

```
docker exec -e DRY_RUN=1 mp3sync /app/sync.sh
```

**Always dry-run first after changing the filter logic.**

### A prebuilt image instead

`.github/workflows/mp3sync-image.yml` builds this directory into
`ghcr.io/<your-github-user>/mp3sync` on every push to `main`. In
`compose.yaml`, swap `build: .` for that image and add
`pull_policy: always`. Then a redeploy is `docker compose pull && docker
compose up -d`.

### Deploy traps

Both hit for real on the test setup, which deployed with Komodo (GitOps):

1. **A redeploy does not rebuild.** A GitOps tool pulls the repo and runs
   `up -d`, which reuses a `build:` image. Scripts baked in with `COPY` kept
   running the old code while the tool reported the new commit as deployed.
2. **Bind-mounting individual files pins their inode.** `git checkout`
   *replaces* files, so a container with a single-file mount went on serving
   the old one.

A prebuilt image plus `pull_policy: always` avoids both. The lesson that
remains: **"deployed: <commit>" means that commit is checked out, not that
its code is running.** Check inside the running container.

`trigger.py` exits when its own file changes on disk, so Docker restarts it.
Inside an image the file never changes, so this only matters if you mount the
source directory into the container for development.

**Secrets:** `HA_TOKEN` belongs in `.env` (gitignored) or your deploy tool's
secret store, never in a compose file you commit.

## Files

| file | role |
|---|---|
| `compose.yaml` | builds and runs the service; reads `.env` |
| `.env.example` | the settings to copy into `.env` |
| `Dockerfile` | alpine + rsync + findutils + python3 |
| `sync.sh` | the sync itself, ported from the macOS script |
| `trigger.py` | webhook + presence poller, serialises runs |
| `ui.html` | the web page, read from disk on every request |
| `apple-touch-icon.png` | iPhone home-screen icon (180×180), rendered from `icon.svg` |
| `icon.svg` | source of that icon (the green R1, drawn from product photos); re-render with `sips -s format png icon.svg --out apple-touch-icon.png` on the Mac, or `rsvg-convert -w 180 icon.svg -o apple-touch-icon.png` |

## Behaviour preserved from the USB script

All six points of `docs/03-usb-sync.md`:

1. `book` untouched — structurally: the player exposes only `music` and
   `podcasts` modules, and rsyncd addresses modules, not paths
2. music mirrored with `--delete`
3. podcasts: 21-day window, newest 2 per show always kept, cover art included
4. old episodes cleaned up
5. single-run locking (two layers, see `docs/08-triggering.md`)
6. progress/completion feedback — Home Assistant push instead of `osascript`

### The one real change: how podcast deletion happens

The USB script mirrored a computed subset **without** `--delete`, then ran a
second pass doing `find`/`rm` directly on the player's filesystem. Over rsyncd
there is no remote shell, so the same rule is expressed as an rsync filter:

```
keep = (everything that is not an .mp3)
     ∪ (.mp3s modified within MAX_DAYS)
     ∪ (newest KEEP_MIN .mp3s per show)
delete = everything else in the module
```

That is the original's rule exactly — "beyond the newest KEEP_MIN **and** older
than MAX_DAYS" — with non-mp3 files explicitly protected so cover art and feed
metadata are never collateral.

**[verified]** against the real tree: 23 of 202 mp3s kept, every show retaining
at least its newest 2, plus 14 cover-art files.

### Orphan shows are protected

A show the player has but the server no longer does would be deleted by that
`--delete` — something the USB original could never do, since it only pruned
within shows it knew about. So `sync.sh` lists the player's shows each run and
emits a protect rule for any the server lacks:

```
P /Some Finished Show/***
```

They stay on the player until removed by hand.

**These rules must come before `+ */` in the filter.** rsync is first-match-
wins: `+ */` would otherwise claim the orphan directory itself, and every run
would end with `cannot delete non-empty directory`.

### Filenames exFAT cannot store

`" * : < > ? \ |` are illegal on exFAT. The device rejects them with EINVAL and
rsync exits 23, so one bad name turns every run into a reported failure. The
flags exclude them. **[verified]** two music files had `?` and `:` and had
never reached the player under the USB sync either; they were renamed at the
source. Podgrab still generates such names from censored episode titles.

## How a sync is asked for

**On the player: open the Tidal app, or add a track to a playlist named
`SYNC`.** Within ~15 s the player calls `GET /sync` here. Why those two, and
how: `docs/08-triggering.md`.

Joining WiFi does **not** sync: `AUTO_SYNC=0` stops the server's poller firing
on the player's appearance, and the firmware no longer triggers when its
daemon starts. The poller still runs, but only to track presence for the UI.

The web UI's **Sync now** remains, as does `GET /sync`.

## Notifications

Optional. Pushed to your phone through the **Home Assistant companion app**
(Gotify has no iOS app). Set `HA_URL`, `HA_TOKEN` and `HA_SERVICE` — the
service is `notify.mobile_app_<device>`; HA lists yours under *Developer
tools → Actions*. Without them, everything else works and the bell shows
that notifications are not configured.

**Configured from the UI** — the bell in the header. Settings live in
`/config/notify.json`; what has already been announced lives in
`/config/notify-state.json`, so nothing repeats after a restart.

| event | default | notes |
|---|---|---|
| Sync finished | when something changed | minimum files changed; lists new episodes |
| Sync failed | on | urgent |
| Large deletion | 50 files | 0 = off; urgent |
| New music | on | a new album folder on the server, once its files have been still for `MUSIC_SETTLE_MIN` (10) minutes; the first run only records the library |
| Episodes waiting | on, from 1 | new episodes not on the player; each announced once |
| Podgrab stuck | on | recent episodes Podgrab failed to download |
| Player not seen | 7 days | 0 = off |
| Quiet hours | off | held messages arrive as one when they end; urgent ones optionally still come |

**The token never reaches the browser.** `HA_URL`, `HA_TOKEN` and `HA_SERVICE`
are environment only; `/api/notify` reports whether the token is set, nothing
more. Create it at **profile → Security → Long-lived access tokens** and set it
in `.env`, never in a committed file. `PUBLIC_URL` is what
tapping a notification opens.

`trigger.py` sends everything; `sync.sh` no longer notifies. A failing
notifier can never fail a sync. Periodic checks run every `NOTIFY_CHECK_MIN`
(5) minutes. "Send test" ignores the master switch and quiet hours.

## Web UI

`http://<server>:8787/` — the player's last known state, and a preview of
exactly what a real sync would push and delete.

| endpoint | purpose |
|---|---|
| `GET /` | the page |
| `GET /apple-touch-icon.png` | home-screen icon (also `-precomposed.png`) |
| `GET /api/state` | player status, last sync, last preview, file lists, listing totals (not the tree) |
| `GET /api/contents` | what is actually on the player (the full tree, ~200 kB) |
| `POST /api/contents` | re-list the player now |
| `POST /api/preview` | run a dry run now |
| `GET /sync` | run a real sync now (also the player's webhook) |
| `GET /status` | plain-text `sync=… player=…` |

The page is `ui.html`, plain HTML + JS with no build step. It is laid out
for a phone first: a sticky action bar with **Preview** and **Sync now** at the
bottom, and three tabs (Music, Podcasts, On player). Music and podcasts are
kept apart: each shows up in its own tab only. It polls
`/api/state` every 3 s while visible and stops when the tab or screen is off.
The file tree is fetched separately, only when the listing changes.

### Three constraints it is built around

1. **The player sleeps.** Asleep, the page shows the *last known* state and
   disables both buttons rather than failing.
2. **`max connections = 1` on the device.** Previews and syncs share one lock,
   so they can never collide. A real sync triggered during a preview waits up
   to 30 s for the lock instead of being dropped.
3. **A preview takes 10–20 s.** It runs in the background; the page polls and
   shows `checking…`.

### Browsing the player

"On the player" lists what the card actually holds, from
`rsync -r rsync://<player>/<module>/`, grouped artist → album → track with
counts and sizes. Cached to `contents.json` and refreshed on demand, because
it costs a connection like everything else.

It immediately earned its keep: it showed **2,992 music files on the card
against 2,989 in the library**. The three extras are `.DS_Store` files macOS
left behind. They are excluded from the sync, and rsync never deletes excluded
files, so they would have sat there indefinitely, invisible.

It also explains a harmless discrepancy: the library has 109 artist folders
but the player lists 107, because two of them contain no syncable
files.

### New episodes

A "New episodes" card compares what the **feeds** hold against what the player
has, using **Podgrab's own API** (`http://podgrab:8080`) — `/podcasts` for
per-show counts, `/podcastitems` for episode dates and download status.

**Apple Podcasts is not consulted, and should not be.** Podgrab already tracks
every feed's full episode list, so querying Apple would re-derive data already
on disk, and would not know what Podgrab had downloaded.

**It does not need the player.** The player sleeps most of the time, so the
check runs against its **last known state** from `contents.json` and says how
old that is ("player as of 2h ago"). Requiring the player awake would mean the
one moment you want to ask "is there anything new?" is exactly the moment you
cannot. It also refreshes itself every `PODGRAB_INTERVAL_MIN` (30), and
`POST /api/podgrab` forces a check.

If the player has never been listed there is nothing to compare against, and
the card says so rather than reporting everything as missing.

It reports two things:

1. **Episodes missing from the player that should be there** — judged by the
   *same* retention rule `sync.sh` applies (within `MAX_DAYS`, or among the
   newest `KEEP_MIN` of a show). Without that, the card flagged two episodes
   as missing that the sync deliberately does not keep — a false alarm that
   would train you to ignore it.
2. **Whether Podgrab is stuck** — any episode published within
   `PODGRAB_RECENT_DAYS` that it has not downloaded.

`DownloadStatus` is `2` for downloaded and `3` for pruned by Podgrab's own
retention; `3` is not a failure and is not flagged.

### Two bugs found while building it, both worth remembering

**A failed check must not look like a clean one.** If a preview fails, rsync
produces an empty file list — identical to "nothing to do". The UI now carries
an `ok` flag per section and says *"could not check"* instead. Showing
"nothing to do" for a check that never ran is a lie the user would act on.

**Status probes compete for the device's only connection.** `player_up()`
opens a TCP connection to rsyncd. The page polls every few seconds, so each
open browser tab was probing the player that often, and a probe landing
between the music and podcast passes could take the slot and fail the sync.
Probes are now cached (`PROBE_TTL`, 20 s) and **never** issued while a
transfer holds the lock — the transfer itself proves the player is up. Only
the poller forces a real probe, since it needs true transitions.

## Knobs

```
PLAYER             required - the player's IP address
MAX_DAYS=21        podcast recency window
KEEP_MIN=2         newest episodes per show, always kept
MODIFY_WINDOW=2    exFAT timestamp granularity - do not lower
COOLDOWN=900       minimum gap between *auto* triggers
AUTO_SYNC=0        1 = also sync whenever the player appears on the network
DRY_RUN=1          preview; set on a one-off `docker exec` run
PROBE_TTL=20       seconds to cache the player's reachability
MAX_LIST=200       max filenames shown per section in the UI
PODGRAB_URL        default http://podgrab:8080
PODGRAB_RECENT_DAYS=21   how recent an undownloaded episode must be to warn
PODGRAB_INTERVAL_MIN=30  how often to re-check the feeds (no player needed)
HA_URL, HA_TOKEN, HA_SERVICE, PUBLIC_URL   notifications, see above
```

Without Podgrab, the "new episodes" card stays empty and the log notes a
failed Podgrab check every `PODGRAB_INTERVAL_MIN`. The sync itself does not
use Podgrab.
