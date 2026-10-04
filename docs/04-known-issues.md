# Known issues and ideas

Nothing here blocks daily use. Each item says what was seen and what is
suspected.

## Issues

- **A `Connection reset by peer` on the first sync after flashing.** The music
  pass failed; the retry succeeded. Not seen since. Unproven cause. Prime
  suspect is the supervisor in `S91netsync`: it stops rsyncd whenever its
  WiFi check fails, so one momentary failure drops an in-flight transfer. If
  it recurs, require **two consecutive** failures before stopping the daemon.
  Diagnosing it needs ADB (`enable_adb` on the card).

- **No sync on a WiFi toggle while the player stays awake** — relevant only
  with `AUTO_SYNC=1`. Turning WiFi off and on produced no transition the
  server's poller could see in time; it was suppressed by the 15-minute
  cooldown. Consider `COOLDOWN=300` if you rely on it.

- **Deleting a track from the `SYNC` playlist may not trigger.** Adding one
  does. See `docs/08-triggering.md`.

- **New files need a library rescan on the player** (*Settings → update music
  database*) before they appear. The player does not watch the card.

## Not yet measured

- Playback quality during a *normal* incremental sync. Only the worst case — a
  full checksum pass — has been measured (`docs/09-flash-and-verify.md`).
- Whether the player stays awake while charging.
- Real transfer throughput for a large addition over 2.4 GHz. A checksum pass
  hashed at ~19 MB/s, but that is reading, not writing.

## Ideas

- **arm64 server support.** The image is plain Alpine and should build for
  arm64; add `linux/arm64` to the workflow's `platforms`. Untested. The
  firmware build itself needs an x86_64 host, because the `muslcc` toolchain
  image is x86_64.
- **Renovate's `dockerfile` manager**, so the image's `FROM` digest is bumped
  automatically.
- **Read the server IP from the card** instead of baking it in at build time,
  so a server move needs no reflash. The card is reachable over USB, so a
  `netsync.conf` there would be easy to edit. It would also widen what the
  daemon trusts to whatever is on the card — weigh that first.
