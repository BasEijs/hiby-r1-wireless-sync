#!/usr/bin/env python3
"""
Age-based retention for Podgrab.

Podgrab has no retention setting of its own (its settings are autoDownload,
downloadOnAdd, initialDownloadCount, append*, generateNFOFile,
maxDownloadConcurrency, dontDownloadDeletedFromDisk and cosmetics), so this
supplies one.

**It deletes through Podgrab's API, never with rm.** Podgrab's own delete
(`GET /podcastitems/<id>/delete`) removes the file AND marks the episode
DownloadStatus 3, so it stays gone. Deleting files behind Podgrab's back is
worse than useless here: this instance has dont_download_deleted_from_disk=0,
so it would simply download them again.

The rule deliberately mirrors the player's: an episode goes if it is older
than MAX_AGE_DAYS *and* not among the newest KEEP_MIN of its show. Without the
KEEP_MIN exception a show that stops publishing loses every episode — and then
the player's mirror deletes them there too. At the time of writing that would
have wiped a show whose newest episode was 69 days old.

DRY_RUN defaults to 1. Deleting ~10 GB should be an explicit decision.
"""
import json
import os
import time
import urllib.parse
import urllib.request

PODGRAB_URL = os.environ.get("PODGRAB_URL", "http://podgrab:8080")
MAX_AGE_DAYS = int(os.environ.get("MAX_AGE_DAYS", "60"))
KEEP_MIN = int(os.environ.get("KEEP_MIN", "2"))
INTERVAL_HOURS = int(os.environ.get("INTERVAL_HOURS", "24"))
DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "2000"))

GOTIFY_URL = os.environ.get("GOTIFY_URL", "")
GOTIFY_TOKEN = os.environ.get("GOTIFY_TOKEN", "")
STATUS_DOWNLOADED = 2


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def api(path):
    with urllib.request.urlopen(f"{PODGRAB_URL}{path}", timeout=30) as r:
        return r.read().decode()


def notify(text):
    if not (GOTIFY_URL and GOTIFY_TOKEN):
        return
    try:
        data = urllib.parse.urlencode(
            {"title": "Podgrab cleanup", "message": text}).encode()
        urllib.request.urlopen(
            f"{GOTIFY_URL}/message?token={GOTIFY_TOKEN}", data=data, timeout=10)
    except Exception as e:
        log(f"notify failed: {e}")


def parse_date(s):
    try:
        return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def candidates():
    """Episodes that may go: too old, and not among the newest KEEP_MIN."""
    items = json.loads(api(f"/podcastitems?count={PAGE_SIZE}"))["podcastItems"]
    by_show = {}
    for it in items:
        if it.get("DownloadStatus") != STATUS_DOWNLOADED:
            continue
        ts = parse_date(it.get("PubDate"))
        if ts is None:
            continue
        show = (it.get("Podcast") or {}).get("Title", "?")
        by_show.setdefault(show, []).append((ts, it))

    now = time.time()
    out = []
    for show, eps in by_show.items():
        eps.sort(key=lambda x: x[0], reverse=True)
        for idx, (ts, it) in enumerate(eps):
            if idx < KEEP_MIN:
                continue                      # always keep the newest few
            age = (now - ts) / 86400
            if age <= MAX_AGE_DAYS:
                continue
            out.append({"show": show, "id": it["ID"],
                        "title": it.get("Title", ""), "days": int(age),
                        "size": it.get("FileSize") or 0})
    out.sort(key=lambda x: (x["show"], -x["days"]))
    return out


def run_once():
    try:
        todo = candidates()
    except Exception as e:
        log(f"could not reach Podgrab: {e}")
        return

    if not todo:
        log("nothing to prune")
        return

    gb = sum(c["size"] for c in todo) / 1e9
    log(f"{len(todo)} episode(s) older than {MAX_AGE_DAYS}d "
        f"(keeping newest {KEEP_MIN} per show), {gb:.1f} GB"
        + ("  [DRY RUN]" if DRY_RUN else ""))

    if DRY_RUN:
        for c in todo[:40]:
            log(f"   would delete: {c['show']} - {c['title'][:50]} ({c['days']}d)")
        if len(todo) > 40:
            log(f"   ... and {len(todo) - 40} more")
        log("DRY_RUN=1, nothing deleted. Set DRY_RUN=0 to act.")
        return

    ok = fail = 0
    for c in todo:
        try:
            api(f"/podcastitems/{c['id']}/delete")
            ok += 1
        except Exception as e:
            fail += 1
            log(f"   FAILED {c['show']} - {c['title'][:40]}: {e}")
        time.sleep(0.2)          # be gentle with a small Go server

    msg = f"deleted {ok} episode(s), {gb:.1f} GB freed" + (f", {fail} failed" if fail else "")
    log(msg)
    notify(msg)


if __name__ == "__main__":
    log(f"podgrab-prune: older than {MAX_AGE_DAYS}d, keep newest {KEEP_MIN}, "
        f"every {INTERVAL_HOURS}h, dry_run={DRY_RUN}")
    while True:
        run_once()
        time.sleep(INTERVAL_HOURS * 3600)
