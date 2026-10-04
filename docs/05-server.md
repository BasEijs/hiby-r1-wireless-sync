# What the server needs

The server does three jobs: it builds the firmware (once), it runs the sync,
and it receives the player's sync requests. The test setup was an Ubuntu
22.04 VM (x86_64, 2 vCPU, 15 GB RAM) with Docker; much less would do.

## Requirements

| | |
|---|---|
| CPU | **x86_64** for the firmware build (the cross toolchain image is x86_64). The sync service itself is plain Alpine and should run on arm64 too — untested |
| software | Docker with compose; `curl` for the build |
| data | the music library and podcast folder **on local disk**. Syncing from a network share works, but sends every byte across the network twice |
| network | a fixed IP (DHCP reservation). It is baked into the firmware, and the player only accepts rsync connections from it |
| port | `8787/tcp` reachable from the player — that is where it asks for syncs |

## Library layout

```
<MUSIC_DIR>/<artist>/<album>/<track>      mirrored as-is, with --delete
<PODCAST_DIR>/<show>/<episode>.mp3        rolling window per show
<PODCAST_DIR>/<show>/<cover>.jpg|png      always kept
```

Any layout under `MUSIC_DIR` works: it is mirrored verbatim. The podcast
retention rule needs **one subfolder per show** — that is what Podgrab
produces.

**Filenames:** `" * : < > ? \ |` are illegal on exFAT. The sync skips such
files rather than fail; rename them at the source if you want them on the
player. Podgrab generates them from censored episode titles.

## Recommendations

1. **Mount the sources read-only** into the container (the compose file
   does). The sync only reads them, so a bug cannot damage a library that
   Plex, Navidrome or anything else also uses.
2. **Notifications are optional.** Home Assistant's companion app is the iOS
   route; Gotify works for `podgrab-prune` but has no iOS app.
3. **Podgrab, if you use it,** should share a Docker network with the sync
   container so it is reachable by name. That powers the "new episodes" card
   in the UI, nothing else.

## If you deploy with GitOps (Komodo, Portainer stacks, Argo...)

One trap, hit three times on the test setup: **a tool reporting "deployed:
<commit>" means that commit is checked out, not that its code is running.**
A redeploy that runs `docker compose up -d` does not rebuild a `build:`
image, and does not restart a container whose compose config is unchanged.
Use a prebuilt image with `pull_policy: always` (the GitHub workflow in this
repo publishes one), and check inside the running container after a deploy.
See `server/mp3sync/README.md` §"Deploy traps".
