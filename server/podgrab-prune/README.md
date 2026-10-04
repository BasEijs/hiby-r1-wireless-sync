# podgrab-prune — age-based retention for Podgrab

Deletes episodes older than `MAX_AGE_DAYS`, **except** the newest `KEEP_MIN`
of each show. Optional: the sync works without it. It only keeps the
*server's* podcast folder from growing forever.

## Why this exists

**Podgrab has no retention setting.** Its settings are `autoDownload`,
`downloadOnAdd`, `initialDownloadCount`, `appendDateToFileName`,
`appendEpisodeNumberToFileName`, `generateNFOFile`,
`downloadEpisodeImages`, `maxDownloadConcurrency`,
`dontDownloadDeletedFromDisk`, `baseUrl`, `userAgent` and dark mode. Nothing
age-based. Verified against the running instance's settings page and database.

## Two things that make the obvious approach wrong

**1. Do not use `rm`.** With `dont_download_deleted_from_disk = 0` (as on the test setup),
Podgrab re-downloads anything that vanishes from disk. A `find -delete`
cron would loop forever, burning bandwidth. Deletion goes through Podgrab's
own endpoint instead:

```
GET /podcastitems/<id>/delete
```

which removes the file **and** marks the episode `DownloadStatus 3`, so it
stays deleted.

**2. Keep the newest few, however old.** The player keeps the newest
`KEEP_MIN` of every show regardless of age. A pure age rule would empty a show
that had simply stopped publishing — and the player's mirror would then delete
those episodes there too. On the test setup, one show had last
published **69 days ago**: a strict 60-day rule would have erased it from the
server and then from the player. With `KEEP_MIN=2` it retains 2 of its 13.

## Measured on the test setup

204 downloaded episodes across 7 shows. At `MAX_AGE_DAYS=60`, `KEEP_MIN=2`,
the first run deleted **160 episodes, 10.3 GB** (13 G → 2.8 G). The player was
unaffected: the next sync had 0 to send and 0 to delete, because the player
keeps a shorter window anyway. The dormant show kept its newest 2.

## Run it

1. It must reach Podgrab by container name, so it joins Podgrab's Docker
   network. Find it with `docker inspect podgrab -f '{{json .NetworkSettings.Networks}}'`.
2. Start it — **in dry-run mode**, which logs and deletes nothing:
   ```
   PODGRAB_NETWORK=<that network> docker compose up -d --build
   docker logs podgrab-prune
   ```
3. When the log lists what you expect, arm it: set `DRY_RUN=0` (in `.env`
   or your deploy tool's environment) and recreate the container. Set it back
   to `1`, or remove it, to disarm.

The compose file reads `${DRY_RUN:-1}`, so a fresh deploy never deletes.
Keep it that way: a literal `DRY_RUN=1` in the compose file could not be
overridden from a deploy tool's environment, which only feeds `${VAR}`
substitutions.

Notifications: set `GOTIFY_URL` and `GOTIFY_TOKEN` together for a message per
cleanup. With either unset it runs silently.

`DownloadStatus` is `2` for downloaded, `3` for deleted. Only `2` is
considered; `3` is already gone.

## Knobs

```
MAX_AGE_DAYS=60     delete beyond this age
KEEP_MIN=2          never drop a show below this many episodes
INTERVAL_HOURS=24   how often to run
DRY_RUN=1           1 = log only. Deleting 10 GB should be deliberate.
```
