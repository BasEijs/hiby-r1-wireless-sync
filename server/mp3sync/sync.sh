#!/bin/sh
#
# Wireless sync: Ubuntu server -> HiBy R1 rsync daemon.
# Port of reference/mp3sync.sh (macOS/USB) per docs/02-plan.md.
#
# The player exposes exactly two rsyncd modules, music and podcasts. rsyncd
# addresses modules, not paths, so nothing here can reach the card's book
# folder even by mistake. Do not add a module or a path that could.
set -u

PLAYER="${PLAYER:?set PLAYER to the IP address of the player}"
MUSIC_SRC="${MUSIC_SRC:-/srv/music}"
POD_SRC="${POD_SRC:-/srv/podcasts}"
MAX_DAYS="${MAX_DAYS:-21}"
KEEP_MIN="${KEEP_MIN:-2}"
DRY_RUN="${DRY_RUN:-0}"
MODIFY_WINDOW="${MODIFY_WINDOW:-2}"   # exFAT stores mtimes at 2s granularity
TIMEOUT="${TIMEOUT:-300}"             # abort a stalled transfer rather than hang
STATE="${STATE:-/config}"
LOCK="$STATE/sync.lock"
LOG="$STATE/sync.log"

# No notifications here: trigger.py sends them after this exits, from the
# summary written at the end. It holds the settings and the HA token.
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

# Count matching lines, always printing exactly one number.
#
# 'grep -c' prints 0 AND exits 1 when nothing matches, so the obvious
# "grep -c ... || echo 0" prints TWO zeros - which corrupted the summary file
# the web UI parses (music_send=0 followed by a bare 0).
count() {
	[ -f "$2" ] || { echo 0; return; }
	c=$(grep -c "$1" "$2" 2>/dev/null)
	echo "${c:-0}"
}

# --- preconditions ------------------------------------------------------
if ! rsync "rsync://$PLAYER/" >/dev/null 2>&1; then
	log "player not reachable at $PLAYER - nothing to do"
	exit 0
fi

if ! mkdir "$LOCK" 2>/dev/null; then
	log "another sync is already running - exiting"
	exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

# --timeout matters here: the player is on 2.4GHz WiFi and does drop. Without
# it a dead socket leaves rsync waiting on the kernel's TCP timeout, i.e. hours.
# With it the sync fails promptly and the next trigger starts a fresh one.
# The trailing exclude drops names exFAT cannot store (" * : < > ? \ |).
# Without it the device's driver rejects them with EINVAL, rsync exits 23, and
# every run reports FAILED over a file that can never be written. Podgrab
# generates such names from censored episode titles, so this is not rare.
FLAGS="-rt --modify-window=$MODIFY_WINDOW --timeout=$TIMEOUT"
FLAGS="$FLAGS --exclude=.DS_Store --exclude=._* --exclude=*[\"*:<>?\\|]*"

# Machine-readable output for the web UI. %i is rsync's itemize field, so a
# deletion appears as "*deleting|path" and a file being sent as "<f+++++++++|path".
# Note the "<": rsync marks a transfer TO the remote with "<" and one received
# locally with ">". We always push, so it is "<".
# trigger.py parses these; keeping the parsing in Python avoids building JSON
# in shell.
FLAGS="$FLAGS --out-format=%i|%n"

if [ "$DRY_RUN" = 1 ]; then
	FLAGS="$FLAGS --dry-run"
	PREFIX="$STATE/preview"
else
	PREFIX="$STATE/last"
fi

log "=== sync start (dry_run=$DRY_RUN) ==="
STATUS=""

# --- protect rules, computed BEFORE anything holds the connection ---------
#
# The player's rsyncd runs with "max connections = 1". Listing its modules
# while the music transfer is finishing gets refused, which silently produced
# an empty protect list and the warning "cannot delete non-empty directory".
# So do it first, and retry.
#
# Note this is belt-and-braces, not a safety mechanism: rsync's --delete does
# NOT remove files excluded by a filter (that would need --delete-excluded),
# so orphan episodes are already safe. These rules make the intent explicit
# and stop rsync trying to remove the directory on every run.
PROTECT="$STATE/podcast.protect"
: > "$PROTECT"
for attempt in 1 2 3; do
	listing=$(rsync "rsync://$PLAYER/podcasts/" 2>/dev/null) && break
	log "podcast listing refused (attempt $attempt) - retrying"
	sleep 3
done
if [ -n "${listing:-}" ]; then
	echo "$listing" \
		| awk '$1 ~ /^d/ { $1=$2=$3=$4=""; sub(/^ +/,""); print }' \
		| grep -vx '\.' \
		| while IFS= read -r show; do
			[ -z "$show" ] && continue
			[ -d "$POD_SRC/$show" ] && continue
			echo "P /$show/***" >> "$PROTECT"
			log "protecting orphan show: $show"
		done
else
	log "WARNING: could not list the player's podcasts - no protect rules"
fi

# --- music: full mirror, with deletes -----------------------------------
if [ -d "$MUSIC_SRC" ]; then
	if rsync $FLAGS --delete "$MUSIC_SRC/" "rsync://$PLAYER/music/" \
			>"$PREFIX-music.out" 2>>"$LOG"; then
		STATUS="music ok"
	else
		STATUS="music FAILED"
	fi
	log "music: $(count '^[<>]' "$PREFIX-music.out") to send, $(count '^\*deleting' "$PREFIX-music.out") to delete"
else
	STATUS="music source missing"
fi
log "$STATUS"

# --- podcasts: selective, with deletes expressed as a filter ------------
#
# The USB original mirrored a computed subset WITHOUT --delete, then ran a
# second pass doing find/rm on the player. Over rsyncd there is no remote
# shell, so the same rule is expressed as an rsync filter instead.
#
# Keep, and therefore never delete:
#   1. anything that is not an .mp3      (cover art, feed metadata)
#   2. .mp3s modified within MAX_DAYS
#   3. the newest KEEP_MIN .mp3s of every show, whatever their age
# Everything else in the module is deleted - which is exactly the original's
# rule: beyond the newest KEEP_MIN *and* older than MAX_DAYS.
if [ -d "$POD_SRC" ]; then
	FILTER="$STATE/podcast.filter"
	{
		cat "$PROTECT" 2>/dev/null

		# NOTE: the protect rules must precede "+ */". rsync is first-match-
		# wins, so "+ */" would otherwise claim the orphan directory itself
		# and rsync would try (and fail) to delete it every run.
		echo "+ */"

		(
			cd "$POD_SRC" || exit 1
			find . -type f ! -iname '*.mp3' ! -name '._*' ! -name '.DS_Store'
			find . -type f -iname '*.mp3' -mtime -"$MAX_DAYS" ! -name '._*'
			find . -mindepth 1 -maxdepth 1 -type d | while IFS= read -r show; do
				find "$show" -type f -iname '*.mp3' ! -name '._*' -printf '%T@ %p\n' \
					| sort -rn | head -n "$KEEP_MIN" | cut -d' ' -f2-
			done
		) | sed 's|^\./||' | sort -u | sed 's|^|+ /|'
		echo "- *"
	} > "$FILTER"

	log "podcast filter: $(grep -c '^+ /' "$FILTER") files kept"

	if rsync $FLAGS --delete --filter="merge $FILTER" \
			"$POD_SRC/" "rsync://$PLAYER/podcasts/" \
			>"$PREFIX-podcasts.out" 2>>"$LOG"; then
		STATUS="$STATUS, podcasts ok"
	else
		STATUS="$STATUS, podcasts FAILED"
	fi
	log "podcasts: $(count '^[<>]' "$PREFIX-podcasts.out") to send, $(count '^\*deleting' "$PREFIX-podcasts.out") to delete"
else
	STATUS="$STATUS, podcast source missing"
fi

# Summary for the web UI. Written for both modes, to separate files.
{
	echo "mode=$([ "$DRY_RUN" = 1 ] && echo preview || echo sync)"
	echo "finished=$(date '+%Y-%m-%d %H:%M:%S')"
	echo "status=$STATUS"
	echo "player=$PLAYER"
	echo "music_send=$(count '^[<>]' "$PREFIX-music.out")"
	echo "music_delete=$(count '^\*deleting' "$PREFIX-music.out")"
	echo "pod_send=$(count '^[<>]' "$PREFIX-podcasts.out")"
	echo "pod_delete=$(count '^\*deleting' "$PREFIX-podcasts.out")"
} > "$PREFIX-summary"

log "=== sync done: $STATUS ==="
