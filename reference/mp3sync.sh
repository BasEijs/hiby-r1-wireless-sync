#!/bin/bash
PLAYER="/Volumes/HibyR1"
MUSIC_SRC="/Volumes/music/"
MUSIC_DEST="$PLAYER/Music"
POD_SRC="/Volumes/fileserver/podgrab"
POD_DEST="$PLAYER/Podcasts"
MAX_DAYS=21
KEEP_MIN=2                                        # newest episodes per show always kept
DELETE_OLD_PODCASTS="${DELETE_OLD_PODCASTS:-1}"   # 1 = remove old episodes (beyond KEEP_MIN)
DRY_RUN="${DRY_RUN:-0}"                           # run as: DRY_RUN=1 ~/bin/mp3sync.sh to preview
RSYNC=/opt/homebrew/bin/rsync
LOCK=/tmp/mp3sync.lock

[ -d "$PLAYER" ] || exit 0
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK"' EXIT

notify() { osascript -e "display notification \"$1\" with title \"HibyR1 sync\""; }
newest() { find "$1" -type f -iname '*.mp3' ! -name '._*' -exec stat -f '%m %N' {} + | sort -rn | cut -d' ' -f2-; }

FLAGS=(-rtv --modify-window=2 --exclude='.DS_Store' --exclude='._*')
[ "$DRY_RUN" = 1 ] && FLAGS+=(--dry-run)
echo "=== $(date) ==="
notify "Sync started"

# Music: full mirror
if [ -d "$MUSIC_SRC" ]; then
  mkdir -p "$MUSIC_DEST"
  if "$RSYNC" "${FLAGS[@]}" --delete "$MUSIC_SRC" "$MUSIC_DEST/"; then
    STATUS="Music ok"
  else
    STATUS="Music FAILED"
  fi
else
  STATUS="Music share not mounted"
fi

notify "$STATUS, now syncing podcasts"
# Podcasts: recent files + newest KEEP_MIN episodes per show + cover images
if [ -d "$POD_SRC" ]; then
  mkdir -p "$POD_DEST"
  LIST=/tmp/mp3sync-podlist.txt
  (
    cd "$POD_SRC" || exit 1
    find . -type f -mtime -"$MAX_DAYS" ! -name '._*' ! -name '.DS_Store'
    find . -type f \( -iname '*.jpg' -o -iname '*.png' \) ! -name '._*'
    find . -mindepth 1 -maxdepth 1 -type d | while IFS= read -r show; do
      newest "$show" | head -n "$KEEP_MIN"
    done
  ) | sort -u > "$LIST"
  if "$RSYNC" "${FLAGS[@]}" --files-from="$LIST" "$POD_SRC/" "$POD_DEST/"; then
    STATUS="$STATUS, podcasts ok"
  else
    STATUS="$STATUS, podcasts FAILED"
  fi
  if [ "$DELETE_OLD_PODCASTS" = 1 ]; then
    find "$POD_DEST" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r show; do
      newest "$show" | tail -n +$((KEEP_MIN + 1)) | while IFS= read -r f; do
        [ -n "$(find "$f" -mtime +"$MAX_DAYS")" ] || continue
        if [ "$DRY_RUN" = 1 ]; then echo "would delete: $f"; else rm -v "$f"; fi
      done
    done
    [ "$DRY_RUN" = 0 ] && find "$POD_DEST" -mindepth 1 -type d -empty -delete
  fi
else
  STATUS="$STATUS, podcast share not mounted"
fi

[ "$DRY_RUN" = 0 ] && dot_clean -m "$MUSIC_DEST" 2>/dev/null && dot_clean -m "$POD_DEST" 2>/dev/null
notify "$STATUS$([ "$DRY_RUN" = 1 ] && echo ' (dry run)')"
