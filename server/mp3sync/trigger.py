#!/usr/bin/env python3
"""
Trigger + status UI for the HiBy R1 wireless sync.

Sync starts two ways, per docs/08-triggering.md:

1. The player asks. S91netsync wgets /sync as soon as its rsync daemon starts
   serving, so powering the player on - or toggling its WiFi - is the trigger.
2. The server notices. A poller watches port 873 and fires on closed -> open,
   subject to a cooldown.

The UI adds a third, manual path plus a preview: a dry run showing exactly
what a real sync would push and delete. A preview needs the player awake, and
the player's rsyncd allows only ONE connection at a time - so previews and
syncs are serialised through a single lock.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAYER = os.environ.get("PLAYER", "")
PLAYER_PORT = int(os.environ.get("PLAYER_PORT", "873"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8787"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
COOLDOWN = int(os.environ.get("COOLDOWN", "900"))
# When 0, the poller only tracks presence for the UI and never starts a sync.
# The player asks for syncs itself (its SYNC playlist), so appearing on the
# network is not by itself a request to sync.
AUTO_SYNC = os.environ.get("AUTO_SYNC", "1") != "0"
SYNC_SH = os.environ.get("SYNC_SH", "/app/sync.sh")
STATE = os.environ.get("STATE", "/config")
MAX_LIST = int(os.environ.get("MAX_LIST", "200"))

_lock = threading.Lock()
_last_auto = 0.0
_running = None          # "sync" | "preview" | None
_player_seen = None      # last time the player answered
_player_cache = (0.0, False)   # (checked_at, up)

# The player's rsyncd allows ONE connection. Every probe consumes that slot
# briefly, so probing must be rare:
#   - the UI polls /api/state every few seconds, and each open browser tab
#     would otherwise probe the player that often
#   - a probe landing between a sync's music and podcast passes can take the
#     slot and make the sync fail
# So: cache the result, and never probe at all while a sync or preview holds
# the lock (the transfer itself already proves the player is up).
PROBE_TTL = int(os.environ.get("PROBE_TTL", "20"))


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def player_up(force=False):
    """Is the player reachable? Cached, and never probed mid-transfer."""
    global _player_seen, _player_cache
    checked_at, cached = _player_cache
    now = time.time()

    if _running is not None:
        # A transfer is in flight, which means it is up. Do not take the slot.
        return True
    if not force and now - checked_at < PROBE_TTL:
        return cached

    try:
        with socket.create_connection((PLAYER, PLAYER_PORT), timeout=3):
            _player_seen = now
            _player_cache = (now, True)
            return True
    except OSError:
        _player_cache = (now, False)
        return False


def _read_summary(prefix):
    """Parse the key=value summary sync.sh writes."""
    path = os.path.join(STATE, f"{prefix}-summary")
    out = {}
    try:
        with open(path) as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k] = v
    except OSError:
        return None
    out["age_seconds"] = int(time.time() - os.path.getmtime(path))
    return out


def _section_ok(summary, section):
    """Did this section's rsync actually succeed?

    A failed check produces an empty file list, which is indistinguishable
    from 'nothing to do' unless we look at the status. Showing 'nothing to do'
    for a check that never ran would be a lie the user acts on.
    """
    if not summary:
        return None
    status = summary.get("status", "")
    name = "music" if section == "music" else "podcasts"
    if f"{name} ok" in status:
        return True
    if f"{name} FAILED" in status:
        return False
    return None


def _read_changes(prefix, section):
    """Split rsync's itemized output into what would be sent vs deleted.

    Lines are '<itemize>|<path>'. A deletion is '*deleting'; a file being sent
    starts with '>'. Directory creations ('cd') are noise here - the user cares
    about files.
    """
    path = os.path.join(STATE, f"{prefix}-{section}.out")
    send, delete = [], []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if "|" not in line:
                    continue
                flag, name = line.split("|", 1)
                if flag.startswith("*deleting"):
                    delete.append(name)
                elif flag[:1] in ("<", ">"):
                    # rsync itemises a transfer TO the remote as "<" and one
                    # received locally as ">". We always push to the player's
                    # daemon, so it is "<". Matching only ">" made every
                    # "to send" count read 0 - invisible while the library
                    # happened to be in sync, then wrong the moment an album
                    # was added.
                    send.append(name)
    except OSError:
        pass
    return {
        "send_total": len(send),
        "delete_total": len(delete),
        "send": send[:MAX_LIST],
        "delete": delete[:MAX_LIST],
        "truncated": len(send) > MAX_LIST or len(delete) > MAX_LIST,
    }


def _changes_with_status(prefix, section):
    c = _read_changes(prefix, section)
    c["ok"] = _section_ok(_read_summary(prefix), section)
    return c


LIST_RE = __import__("re").compile(r"^(\S+)\s+([\d,]+)\s+(\S+)\s+(\S+)\s+(.*)$")


def _fetch_module(module):
    """Recursive listing of one module on the player.

    rsync's list output is 'perms size date time path'; sizes carry thousands
    separators and paths may contain spaces, so split from the left exactly
    four times.
    """
    out = subprocess.run(
        ["rsync", "-r", f"rsync://{PLAYER}/{module}/"],
        capture_output=True, text=True, timeout=300,
    )
    if out.returncode != 0:
        return {"ok": False, "error": (out.stderr or "").strip()[:200]}

    top = {}
    files = total = 0
    for line in out.stdout.splitlines():
        m = LIST_RE.match(line)
        if not m:
            continue
        perms, size, _d, _t, path = m.groups()
        if perms.startswith("d") or path == ".":
            continue
        size = int(size.replace(",", ""))
        files += 1
        total += size
        parts = path.split("/")
        a = parts[0]
        b = parts[1] if len(parts) > 2 else ""      # album, or "" when flat
        name = parts[-1]
        grp = top.setdefault(a, {"files": 0, "bytes": 0, "sub": {}})
        grp["files"] += 1
        grp["bytes"] += size
        sub = grp["sub"].setdefault(b, {"files": 0, "bytes": 0, "names": []})
        sub["files"] += 1
        sub["bytes"] += size
        if len(sub["names"]) < 500:
            sub["names"].append(name)
    return {"ok": True, "files": files, "bytes": total, "top": top}


PODGRAB_URL = os.environ.get("PODGRAB_URL", "http://podgrab:8080")
PODGRAB_RECENT_DAYS = int(os.environ.get("PODGRAB_RECENT_DAYS", "21"))
PODGRAB_INTERVAL = int(os.environ.get("PODGRAB_INTERVAL_MIN", "30"))
# The same retention rule sync.sh applies, so the UI can tell "deliberately
# not kept" apart from "missing when it should be there".
MAX_DAYS = int(os.environ.get("MAX_DAYS", "21"))
KEEP_MIN = int(os.environ.get("KEEP_MIN", "2"))


def _podgrab(path):
    import urllib.request
    with urllib.request.urlopen(f"{PODGRAB_URL}{path}", timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_podgrab(device_files):
    """What the feeds hold, versus what the player has.

    Podgrab already tracks every feed's full episode list, so asking Apple
    Podcasts would re-derive data we already own. DownloadStatus: 2 is
    downloaded, 3 is pruned by Podgrab's own retention.

    device_files maps show -> set of filenames actually on the card.
    """
    shows = _podgrab("/podcasts")
    items = _podgrab("/podcastitems?count=300")["podcastItems"]

    now = time.time()
    by_show = {}
    stuck = []
    for it in items:
        pub = it.get("PubDate") or ""
        try:
            ts = time.mktime(time.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        show = (it.get("Podcast") or {}).get("Title", "?")
        fname = os.path.basename(it.get("DownloadPath") or "")
        age_days = (now - ts) / 86400
        status = it.get("DownloadStatus")

        # Recent but never fetched => Podgrab may be stuck. 3 = pruned, not stuck.
        if age_days <= PODGRAB_RECENT_DAYS and status not in (2, 3):
            stuck.append({"show": show, "title": it.get("Title", ""),
                          "days": int(age_days), "status": status})

        if status != 2:
            continue
        rec = by_show.setdefault(show, [])
        if len(rec) < 4:
            # sync.sh keeps an episode if it is within MAX_DAYS, or among the
            # newest KEEP_MIN of its show. Anything else is meant to be absent.
            expected = len(rec) < KEEP_MIN or age_days <= MAX_DAYS
            on_device = fname in device_files.get(show, set())
            rec.append({
                "title": it.get("Title", ""),
                "file": fname,
                "date": pub[:10],
                "days": int(age_days),
                "on_device": on_device,
                "expected": expected,
                "problem": expected and not on_device,
            })

    out = []
    for s in shows:
        title = s.get("Title", "?")
        out.append({
            "show": title,
            "feed_total": s.get("AllEpisodesCount", 0),
            "downloaded": s.get("DownloadedEpisodesCount", 0),
            "paused": bool(s.get("IsPaused")),
            "recent": by_show.get(title, []),
        })
    out.sort(key=lambda x: x["show"].lower())
    return {"ok": True, "shows": out, "stuck": stuck,
            "recent_days": PODGRAB_RECENT_DAYS}


def _device_files_from_cache():
    """Episode filenames the player had at the last listing, per show.

    Returns (mapping, age_seconds). The player sleeps most of the time, so the
    feed comparison must work from its last known state rather than demanding
    it be awake - otherwise the one moment you want to know "is there anything
    new?" is exactly the moment you cannot ask.
    """
    c = read_contents()
    if not c:
        return {}, None
    pod = c.get("podcasts") or {}
    if not pod.get("ok"):
        return {}, c.get("age_seconds")
    out = {}
    for show, grp in pod["top"].items():
        names = set()
        for sub in grp["sub"].values():
            names.update(sub["names"])
        out[show] = names
    return out, c.get("age_seconds")


def refresh_podgrab():
    """Compare feeds against the player's last known state. No player needed."""
    device_files, device_age = _device_files_from_cache()
    try:
        data = fetch_podgrab(device_files)
    except Exception as e:
        data = {"ok": False, "error": str(e)[:200]}
    data["generated"] = int(time.time())
    data["device_age_seconds"] = device_age
    data["device_known"] = bool(device_files)
    tmp = os.path.join(STATE, "podgrab.json.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(STATE, "podgrab.json"))
    except OSError as e:
        log(f"could not write podgrab.json: {e}")
    return data


def read_podgrab():
    try:
        with open(os.path.join(STATE, "podgrab.json")) as f:
            d = json.load(f)
        d["age_seconds"] = int(time.time() - d.get("generated", 0))
        return d
    except (OSError, ValueError):
        return None


def podgrab_poller():
    """Keep the feed comparison fresh on its own. Touches only Podgrab."""
    while True:
        try:
            refresh_podgrab()
        except Exception as e:
            log(f"podgrab refresh failed: {e}")
        time.sleep(PODGRAB_INTERVAL * 60)


def fetch_contents():
    """What is actually on the player. Shares the lock: one connection only."""
    global _running
    if not _lock.acquire(blocking=False):
        log(f"busy ({_running}), not listing the player")
        return False
    _running = "listing"
    try:
        log("listing the player")
        data = {
            "generated": int(time.time()),
            "music": _fetch_module("music"),
            "podcasts": _fetch_module("podcasts"),
        }
        # Which episode files the card actually holds, per show.
        device_files = {}
        pod = data["podcasts"]
        if pod.get("ok"):
            for show, grp in pod["top"].items():
                names = set()
                for sub in grp["sub"].values():
                    names.update(sub["names"])
                device_files[show] = names
        try:
            pgd = fetch_podgrab(device_files)
            pgd["generated"] = int(time.time())
            pgd["device_age_seconds"] = 0
            pgd["device_known"] = bool(device_files)
            data["podgrab"] = pgd
            with open(os.path.join(STATE, "podgrab.json"), "w") as f:
                json.dump(pgd, f)
        except Exception as e:
            data["podgrab"] = {"ok": False, "error": str(e)[:200]}
        tmp = os.path.join(STATE, "contents.json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(STATE, "contents.json"))
        log("listing done")
        return True
    except Exception as e:
        log(f"listing failed: {e}")
        return False
    finally:
        _running = None
        _lock.release()


def read_contents():
    try:
        with open(os.path.join(STATE, "contents.json")) as f:
            d = json.load(f)
        d["age_seconds"] = int(time.time() - d.get("generated", 0))
        return d
    except (OSError, ValueError):
        return None


def contents_summary():
    """The listing without its file tree.

    The UI polls /api/state every few seconds; the full tree is ~200 kB and
    changes only when the player is re-listed. The page fetches the tree from
    /api/contents when `generated` moves.
    """
    c = read_contents()
    if not c:
        return None
    out = {"generated": c.get("generated"), "age_seconds": c.get("age_seconds")}
    for m in ("music", "podcasts"):
        d = c.get(m) or {}
        out[m] = {k: d.get(k) for k in ("ok", "files", "bytes", "error")}
    return out


def snapshot():
    up = player_up()
    return {
        "player": {
            "host": PLAYER,
            "up": up,
            "last_seen": int(_player_seen) if _player_seen else None,
        },
        "running": _running,
        "last_sync": _read_summary("last"),
        "last_sync_changes": {
            "music": _changes_with_status("last", "music"),
            "podcasts": _changes_with_status("last", "podcasts"),
        },
        "preview": _read_summary("preview"),
        "contents": contents_summary(),
        "podgrab": read_podgrab(),
        "music_compare": music_compare(),
        "preview_changes": {
            "music": _changes_with_status("preview", "music"),
            "podcasts": _changes_with_status("preview", "podcasts"),
        },
    }


# --- notifications ----------------------------------------------------------
#
# Home Assistant's companion app is the iPhone route: Gotify has no iOS app.
# HA_TOKEN lives only in the container's environment and never
# reaches the browser - /api/notify reports whether it is set, nothing more.
# Everything else is tuned from the UI and kept in notify.json.
#
# A notifier must never fail a sync: every send swallows its own errors.
HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HA_SERVICE = os.environ.get("HA_SERVICE", "notify.notify")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")     # tapping a notification opens this
NOTIFY_CHECK_MIN = int(os.environ.get("NOTIFY_CHECK_MIN", "5"))
MUSIC_SRC = os.environ.get("MUSIC_SRC", "/srv/music")
# Lidarr imports an album track by track. An album counts as arrived once its
# newest file is this old, so a half-imported one is not announced.
MUSIC_SETTLE = int(os.environ.get("MUSIC_SETTLE_MIN", "10")) * 60
AUDIO_RE = re.compile(r"\.(flac|mp3|m4a|aac|ogg|opus|wav|alac)$", re.I)

NOTIFY_DEFAULTS = {
    "enabled": True,
    "sync_done": "changes",      # always | changes | never
    "sync_min_changes": 1,
    "sync_failed": True,
    "big_delete": 50,            # files deleted in one sync; 0 = off
    "new_music": True,
    "new_episodes": True,
    "new_episodes_min": 1,
    "podgrab_stuck": True,
    "absent_days": 7,            # 0 = off
    "quiet": False,
    "quiet_start": "22:00",
    "quiet_end": "08:00",
    "quiet_urgent": True,        # failures and large deletions ignore quiet hours
}
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_notify_lock = threading.RLock()


def _load_json(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(name, data):
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(STATE, name))


def clean_settings(raw):
    """Defaults, overlaid with whatever in `raw` is valid. Unknown keys drop."""
    out = dict(NOTIFY_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for k, default in NOTIFY_DEFAULTS.items():
        if k not in raw:
            continue
        v = raw[k]
        # bool before int: bool is a subclass of int.
        if isinstance(default, bool):
            out[k] = bool(v)
        elif isinstance(default, int):
            try:
                out[k] = max(0, min(int(v), 10000))
            except (TypeError, ValueError):
                pass
        elif k == "sync_done":
            if v in ("always", "changes", "never"):
                out[k] = v
        elif isinstance(v, str) and HHMM.fullmatch(v):
            out[k] = v
    return out


def load_settings():
    return clean_settings(_load_json("notify.json", {}))


def ha_configured():
    return bool(HA_URL and HA_TOKEN)


def in_quiet(s, now=None):
    if not s["quiet"]:
        return False
    t = time.strftime("%H:%M", time.localtime(now))
    a, b = s["quiet_start"], s["quiet_end"]
    return a <= t < b if a <= b else (t >= a or t < b)


def ha_post(title, message, urgent=False):
    """One push through HA. Returns (ok, detail); never raises.

    detail must never contain the token - it is shown in the UI.
    """
    import urllib.error
    import urllib.request
    if not ha_configured():
        return False, "HA_URL or HA_TOKEN is not set on the server"
    data = {
        "group": "r1-sync",
        "push": {"interruption-level": "time-sensitive" if urgent else "active"},
    }
    if PUBLIC_URL:
        data["url"] = PUBLIC_URL
    req = urllib.request.Request(
        f"{HA_URL}/api/services/{HA_SERVICE.replace('.', '/', 1)}",
        data=json.dumps({"title": title, "message": message, "data": data}).encode(),
        headers={"Authorization": f"Bearer {HA_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return True, f"HA replied {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HA replied {e.code}"
    except Exception as e:
        return False, f"could not reach HA: {getattr(e, 'reason', e)}"[:160]


def notify(title, message, urgent=False):
    """Send, or hold until quiet hours end. Honours the master switch."""
    s = load_settings()
    if not (s["enabled"] and ha_configured()):
        return
    if in_quiet(s) and not (urgent and s["quiet_urgent"]):
        with _notify_lock:
            st = _load_json("notify-state.json", {})
            st["deferred"] = (st.get("deferred", []) + [f"{title}: {message}"])[-20:]
            _save_json("notify-state.json", st)
        log(f"notify held for quiet hours: {title}")
        return
    ok, detail = ha_post(title, message, urgent)
    log(f"notify {'sent' if ok else 'FAILED'}: {title} ({detail})")


def _sync_line(l):
    parts = []
    for label, a, d in (("Music", l["music_send"], l["music_delete"]),
                        ("Podcasts", l["pod_send"], l["pod_delete"])):
        if a or d:
            parts.append(label + " " + " ".join(
                x for x in (f"+{a}" if a else "", f"−{d}" if d else "") if x))
    return " · ".join(parts) or "Nothing changed"


def notify_sync(started):
    """After a real sync: done, failed, or a suspiciously large deletion."""
    s = load_settings()
    l = _read_summary("last")
    # sync.sh exits without a summary when the player is unreachable or the
    # lock is held. A stale summary is an older sync; there is nothing to say.
    if not l or l["age_seconds"] > time.time() - started + 1:
        return
    n = {k: int(l.get(k) or 0)
         for k in ("music_send", "music_delete", "pod_send", "pod_delete")}
    status = l.get("status", "")
    failed = "FAILED" in status or "missing" in status
    deleted = n["music_delete"] + n["pod_delete"]

    if failed and s["sync_failed"]:
        notify("R1 sync failed", status, urgent=True)
    if s["big_delete"] and deleted >= s["big_delete"]:
        notify("R1 sync: large deletion",
               f"{deleted} files removed from the player "
               f"({n['music_delete']} music, {n['pod_delete']} podcasts)",
               urgent=True)
    if failed:
        return

    total = sum(n.values())
    if s["sync_done"] == "always" or (
            s["sync_done"] == "changes" and total and total >= s["sync_min_changes"]):
        msg = _sync_line(n)
        eps = [p.rsplit("/", 1)[-1] for p in _read_changes("last", "podcasts")["send"]
               if p.lower().endswith(".mp3")]
        if eps:
            msg += "\n" + "\n".join(e[:-4] for e in eps[:3])
            if len(eps) > 3:
                msg += f"\n… and {len(eps) - 3} more"
        notify("R1 sync done", msg)


def _last_seen():
    """Latest evidence the player was on the network, surviving restarts."""
    seen = [_player_seen or 0]
    c = read_contents()
    if c:
        seen.append(c.get("generated") or 0)
    l = _read_summary("last")
    if l:
        seen.append(time.time() - l["age_seconds"])
    return max(seen) or None


def _new_items(st, key, current, wanted, minimum=1):
    """Items in `current` not announced yet. Returns them when a message is
    due, else []. Items that went away are forgotten, so they can come back."""
    told = set(st.get(key, [])) & set(current)
    fresh = [k for k in current if k not in told]
    if wanted and fresh and len(current) >= minimum:
        st[key] = sorted(current)
        return fresh
    st[key] = sorted(told)
    return []


def music_albums():
    """Folders under MUSIC_SRC holding audio -> their newest file's mtime.

    ~3000 files take well under a second, so a full walk every check is fine.
    """
    out = {}
    for root, _dirs, files in os.walk(MUSIC_SRC):
        for f in files:
            if f.startswith("._") or not AUDIO_RE.search(f):
                continue
            try:
                m = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            rel = os.path.relpath(root, MUSIC_SRC)
            if rel == ".":
                continue            # loose files at the top are not an album
            out[rel] = max(out.get(rel, 0), m)
    return out


# Names sync.sh excludes because exFAT cannot store them. They never reach the
# player, so counting them as missing would flag the same tracks forever.
EXFAT_BAD = re.compile(r'["*:<>?\\|]')
_music_cmp = (0.0, None)


def _server_music():
    """(artist, album) -> audio filenames, keyed the way _fetch_module keys
    the player: first folder, second folder ("" when flat)."""
    out = {}
    for root, _dirs, files in os.walk(MUSIC_SRC):
        parts = os.path.relpath(root, MUSIC_SRC).split(os.sep)
        if parts == ["."]:
            continue
        key = (parts[0], parts[1] if len(parts) > 1 else "")
        for f in files:
            if f.startswith("._") or not AUDIO_RE.search(f) or EXFAT_BAD.search(f):
                continue
            out.setdefault(key, set()).add(f)
    return out


def music_compare():
    """The server's music against the player's last listing.

    The Music tab otherwise only knows the last Preview, which needs the player
    awake and goes stale the moment Lidarr imports an album - so a new album
    read "up to date" while its notification had already arrived. Like the
    podcast feed check, this works from the last listing: no player needed.
    Cached briefly: /api/state is polled every few seconds.
    """
    global _music_cmp
    at, cached = _music_cmp
    if cached is not None and time.time() - at < 30:
        return cached
    c = read_contents()
    m = (c or {}).get("music") or {}
    if not m.get("ok"):
        out = {"device_known": False}
    else:
        player = {}
        for a, grp in m["top"].items():
            for b, sub in grp["sub"].items():
                player[(a, b)] = {n for n in sub["names"] if AUDIO_RE.search(n)}
        server = _server_music() if os.path.isdir(MUSIC_SRC) else {}
        waiting, removing = [], []
        for key, names in sorted(server.items()):
            have = player.get(key, set())
            missing = len(names - have)
            if missing:
                waiting.append({"path": "/".join(k for k in key if k),
                                "missing": missing, "total": len(names),
                                "new": not have})
        if server:        # an empty walk is a missing mount, not "remove it all"
            for key, names in sorted(player.items()):
                if names and key not in server:
                    removing.append({"path": "/".join(k for k in key if k),
                                     "files": len(names)})
        out = {"device_known": True, "device_age_seconds": c.get("age_seconds"),
               "waiting": waiting, "removing": removing}
    _music_cmp = (time.time(), out)
    return out


def new_music(announce):
    """Album folders that settled since the last check. Returns [] on the
    first run: that only records what is there, or the whole library would
    arrive as "new". Tracked even when `announce` is off, so switching it on
    later brings no backlog."""
    albums = music_albums()
    if not albums:
        # An empty walk is far likelier a missing mount than an empty
        # library. Keep the record rather than re-announce everything later.
        return []
    now = time.time()
    settled = {k for k, m in albums.items() if now - m > MUSIC_SETTLE}
    known = _load_json("music-known.json", None)
    if known is None:
        _save_json("music-known.json", sorted(settled))
        return []
    # Forget removed albums, so one that is re-imported is news again.
    known = set(known) & set(albums)
    fresh = sorted(settled - known)
    _save_json("music-known.json", sorted(known | settled))
    return fresh if announce else []


def check_events():
    """Periodic events: new music, episodes waiting, Podgrab stuck, player absent.

    Each thing is announced once; notify-state.json remembers what was said.
    """
    s = load_settings()
    if not (s["enabled"] and ha_configured()):
        return
    out = []
    with _notify_lock:
        st = _load_json("notify-state.json", {})

        if st.get("deferred") and not in_quiet(s):
            held = st.pop("deferred")
            out.append(("R1 sync: during quiet hours", "\n".join(held[-10:]), False))

        fresh = new_music(s["new_music"])
        if fresh:
            n = len(fresh)
            out.append((f"{n} new album{'s' if n > 1 else ''} on the server",
                        "\n".join(a.replace("/", " — ") for a in fresh[:5])
                        + (f"\n… and {n - 5} more" if n > 5 else ""),
                        False))

        g = read_podgrab()
        if g and g.get("ok") and g.get("device_known"):
            waiting = {f"{sh['show']}/{e['file']}": f"{sh['show']} — {e['title']}"
                       for sh in g.get("shows", []) for e in sh.get("recent", [])
                       if e.get("problem")}
            fresh = _new_items(st, "told_waiting", waiting, s["new_episodes"],
                               s["new_episodes_min"])
            if fresh:
                n = len(waiting)
                out.append((f"{n} episode{'s' if n > 1 else ''} waiting for the R1",
                            "\n".join(waiting[k] for k in fresh[:5])
                            + (f"\n… and {len(fresh) - 5} more" if len(fresh) > 5 else ""),
                            False))

            stuck = {f"{x['show']}/{x['title']}": f"{x['show']} — {x['title']}"
                     for x in g.get("stuck", [])}
            fresh = _new_items(st, "told_stuck", stuck, s["podgrab_stuck"])
            if fresh:
                out.append(("Podgrab is not downloading",
                            "\n".join(stuck[k] for k in fresh[:5]), False))

        seen = _last_seen()
        if (s["absent_days"] and seen and time.time() - seen > s["absent_days"] * 86400
                and st.get("told_absent") != int(seen)):
            days = int((time.time() - seen) / 86400)
            out.append(("R1 not seen",
                        f"The player has been off the network for {days} days. "
                        "Switch it on to sync.", False))
            st["told_absent"] = int(seen)

        _save_json("notify-state.json", st)

    for title, message, urgent in out:
        notify(title, message, urgent)


def notify_info():
    """What the UI may know. The token itself is never included."""
    s = load_settings()
    return {
        "settings": s,
        "ha": {"configured": ha_configured(), "url": HA_URL, "service": HA_SERVICE},
        "quiet_now": in_quiet(s),
    }


def notify_watcher():
    while True:
        time.sleep(NOTIFY_CHECK_MIN * 60)
        try:
            check_events()
        except Exception as e:
            log(f"notify check failed: {e}")


def run_sync(reason, dry_run=False, wait=0):
    """Run sync.sh. Previews and real syncs share one lock, because the
    player's rsyncd accepts a single connection."""
    global _running
    acquired = _lock.acquire(timeout=wait) if wait else _lock.acquire(blocking=False)
    if not acquired:
        log(f"busy ({_running}), ignoring: {reason}")
        return False
    _running = "preview" if dry_run else "sync"
    started = time.time()
    try:
        log(f"{_running} starting ({reason})")
        env = dict(os.environ, DRY_RUN="1" if dry_run else "0")
        result = subprocess.run([SYNC_SH], capture_output=True, text=True, env=env)
        log(f"{_running} finished rc={result.returncode} ({reason})")
    finally:
        _running = None
        _lock.release()
    if not dry_run:
        try:
            notify_sync(started)
        except Exception as e:
            log(f"notify failed: {e}")
    # Re-list while the player is known to be awake. The feed comparison works
    # from the last listing; without this it keeps reporting episodes the sync
    # just sent as missing, and disagrees with a fresh Preview.
    fetch_contents()
    return True


def self_restart_watcher():
    """Exit when this file changes, so Docker restarts us on the new code.

    The scripts are mounted from the repo, but trigger.py is a long-running
    process: a GitOps redeploy (Komodo, say) updates the file while the old code keeps
    running, and `up -d` will not recreate the container when the compose
    config is unchanged. That cost a manual `docker restart` every time.

    compose sets `restart: unless-stopped`, so exiting is a reload.
    """
    me = os.path.abspath(__file__)
    try:
        known = os.path.getmtime(me)
    except OSError:
        return
    while True:
        time.sleep(10)
        try:
            now = os.path.getmtime(me)
        except OSError:
            continue
        if now == known:
            continue
        # Let a half-written file settle before acting on it.
        time.sleep(5)
        try:
            if os.path.getmtime(me) != now:
                continue
        except OSError:
            continue
        if _running is not None:
            log(f"code changed, waiting for {_running} to finish")
            continue
        log("code changed on disk - exiting so Docker restarts us")
        os._exit(0)


def poller():
    global _last_auto
    was_up = player_up(force=True)
    log(f"poller started, player currently {'up' if was_up else 'down'}")
    while True:
        time.sleep(POLL_INTERVAL)
        now_up = player_up(force=True)
        if now_up and not was_up:
            if not AUTO_SYNC:
                log("player appeared (auto-sync disabled; waiting to be asked)")
            elif time.time() - _last_auto < COOLDOWN:
                log("player appeared but still within cooldown, skipping")
            else:
                _last_auto = time.time()
                threading.Thread(
                    target=run_sync, args=("player appeared",), daemon=True
                ).start()

        was_up = now_up


# The page lives in its own file, read on every request: editing it needs no
# restart, and it is easier to work on than HTML inside a Python string.
UI_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")


def page():
    try:
        with open(UI_HTML, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        return f"<p>ui.html missing: {e}</p>"


# Home-screen icon for "Add to Home Screen" in Safari. iOS ignores SVG icons,
# so this is a PNG rendered from icon.svg. It is also probed at these root
# paths without any <link>, hence both names.
ICON_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "apple-touch-icon.png")
ICON_PATHS = ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        if path in ("/", ""):
            self._send(200, page(), "text/html; charset=utf-8")
        elif path in ICON_PATHS:
            try:
                with open(ICON_PNG, "rb") as f:
                    self._send(200, f.read(), "image/png")
            except OSError:
                self._send(404, "not found\n")
        elif path == "/api/podgrab":
            self._send(200, json.dumps(read_podgrab() or {}), "application/json")
        elif path == "/api/contents":
            self._send(200, json.dumps(read_contents() or {}), "application/json")
        elif path == "/api/state":
            self._send(200, json.dumps(snapshot()), "application/json")
        elif path == "/api/notify":
            self._send(200, json.dumps(notify_info()), "application/json")
        elif path == "/sync":
            threading.Thread(target=run_sync, args=("webhook",),
                             kwargs={"wait": 30}, daemon=True).start()
            self._send(202, "sync triggered\n")
        elif path == "/status":
            state = "running" if _lock.locked() else "idle"
            self._send(200, f"sync={state} player={'up' if player_up() else 'down'}\n")
        else:
            self._send(404, "not found\n")

    def do_POST(self):
        if self.path.rstrip("/") == "/api/podgrab":
            threading.Thread(target=refresh_podgrab, daemon=True).start()
            self._send(202, "checking feeds\n")
        elif self.path.rstrip("/") == "/api/contents":
            threading.Thread(target=fetch_contents, daemon=True).start()
            self._send(202, "listing started\n")
        elif self.path.rstrip("/") == "/api/preview":
            threading.Thread(target=run_sync, args=("ui preview",),
                             kwargs={"dry_run": True}, daemon=True).start()
            self._send(202, "preview started\n")
        elif self.path.rstrip("/") == "/api/notify":
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 10000)
                raw = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, "bad json\n")
            with _notify_lock:
                _save_json("notify.json", clean_settings(raw))
            self._send(200, json.dumps(notify_info()), "application/json")
        elif self.path.rstrip("/") == "/api/notify/test":
            # Deliberately ignores the master switch and quiet hours: a test
            # that stays silent at 23:00 would look like a broken setup.
            ok, detail = ha_post("R1 sync test", "Notifications are working.")
            self._send(200, json.dumps({"ok": ok, "detail": detail}),
                       "application/json")
        else:
            self._send(404, "not found\n")

    def log_message(self, fmt, *args):
        if "/api/state" not in (args[0] if args else ""):
            log(f"http {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    if not PLAYER:
        sys.exit("PLAYER is not set - give it the IP address of the player")
    threading.Thread(target=poller, daemon=True).start()
    threading.Thread(target=self_restart_watcher, daemon=True).start()
    threading.Thread(target=podgrab_poller, daemon=True).start()
    threading.Thread(target=notify_watcher, daemon=True).start()
    log(f"listening on :{LISTEN_PORT}, player {PLAYER}:{PLAYER_PORT}")
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
