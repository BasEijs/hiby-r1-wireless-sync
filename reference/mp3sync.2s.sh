#!/bin/bash
LOG="$HOME/Library/Logs/mp3sync.log"
LOCK=/tmp/mp3sync.lock
AUDIO='\.(flac|mp3|m4a)$'

START=$(grep -n '^=== ' "$LOG" 2>/dev/null | tail -1 | cut -d: -f1)
RUN=$(tail -n +"${START:-1}" "$LOG" 2>/dev/null)
WHEN=$(head -1 <<< "$RUN" | sed 's/^=== //; s/ ===$//')
copied() { grep -Ei "$AUDIO" <<< "$RUN" | grep -v -e '^deleting ' -e '^/' ; }
COUNT=$(copied | wc -l | tr -d ' ')

if [ -d "$LOCK" ]; then
  if grep -q '^total size is' <<< "$RUN"; then PHASE="podcasts"; else PHASE="music"; fi
  NOW=$(copied | tail -1 | sed 's#.*/##')
  echo "$COUNT | sfimage=arrow.triangle.2.circlepath"
  echo "---"
  echo "Syncing $PHASE: $COUNT files copied"
  echo "${NOW:-Comparing files...} | length=60"
else
  echo " | sfimage=music.note"
  echo "---"
  echo "Last sync: ${WHEN:-never}"
  echo "Files copied: $COUNT"
fi
echo "Open log | bash=/usr/bin/open param1=$LOG terminal=false"
