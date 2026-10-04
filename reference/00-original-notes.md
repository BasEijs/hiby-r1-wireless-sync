# HiBy R1 — can WiFi sync replace the USB sync?

> The brief this project started from, kept for the record. Some of it turned
> out wrong — see `docs/01-findings.md`.

## Goal
Find out whether the HiBy R1 DAP (<player-ip>) can be synced over WiFi from
this Mac, instead of over USB. If yes, adapt the existing sync script.
If no, say so clearly and stop — the USB setup already works.

## What already works (do not break this)
- `~/bin/mp3sync.sh` — rsync script, runs on USB mount.
- `~/Library/LaunchAgents/<agent>.plist` — launchd, StartOnMount.
- `~/SwiftBar/mp3sync.2s.sh` — menu bar progress indicator.
- Sources: /Volumes/music (music), /Volumes/fileserver/podgrab (podcasts).
- Player folders: Music (full mirror), Podcasts (last 21 days + newest 2 per
  show), book (must never be touched).

## Established facts
- Device: HiBy R1, HiByOS (Linux-based, NOT Android), 2.4GHz WiFi only.
- Vendor docs: wireless transfer only via the HiBy Music phone app (push);
  also AirPlay, DLNA, HiByLink. USB MassStorage is the documented transfer route.
- nmap top-200 scan: 182 closed, one port OPEN: **4001/tcp**.
  No FTP (21), SSH (22), SMB (139/445) listening.
- `curl http://<player-ip>:4001/` → "Connection reset by peer".
  So 4001 accepts TCP but is not HTTP.
- WiFi stays up when the screen sleeps (ping replies) — confirmed.
- ICMP became unresponsive right after the 200-port scan while TCP 4001 still
  accepted connections. Possible rate limiting; use `nmap -Pn`.

## Open questions, in priority order
1. What protocol does 4001 speak? Does it send a banner, or expect the client
   to speak first?
2. Does that protocol support LISTING and DELETING files, or only uploading?
   Listing+deleting is required: the music mirror uses rsync --delete and the
   podcast cleanup removes old episodes.
3. Are there UDP services (DLNA/SSDP 1900, mDNS 5353)? DLNA is usually
   read-only from the device's side, but it may reveal the API.
4. Does HiByOS expose anything only while the phone app is connected?

## Suggested approach
- Passive first: `nmap -Pn -sV -p 4001`, SSDP/mDNS discovery, UDP top ports.
- Then observe: capture traffic between the HiBy Music app (phone, same LAN)
  and the player. Direct phone-to-player traffic is not visible on the Mac by
  default — mirroring or the Mac as a hotspot is needed.
- Only then consider speaking the protocol.

## Constraints
- Be honest about dead ends. A clear "not feasible" is a good outcome.
- Do not modify the working USB scripts until a WiFi path is actually proven.
- No writes to the player's `book` folder, ever.
- Realistic bar: even if uploads work, without list+delete this cannot replace
  the current sync. Say so early rather than building half a solution.
