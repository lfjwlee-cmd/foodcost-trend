#!/usr/bin/env python3
"""Collect yesterday's trending Korean food/menu videos into data/<date>.json.

Runs headless (GitHub Actions) with no API key: yt-dlp reads YouTube's public
search and watch metadata. Every number written comes from yt-dlp's metadata for
that specific video — nothing is estimated, rounded, or filled in.

This step only collects. scripts/verify.py decides whether the result may be
published, and scripts/render.py writes the pages.
"""

import json
import os
import sys
import time
import datetime as dt
from pathlib import Path
from urllib.parse import quote

from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

KST = dt.timezone(dt.timedelta(hours=9))
# YouTube's "this week" upload filter. There is no yesterday-only filter, so this
# only narrows the pool; the exact-timestamp check below is what decides.
SP_THIS_WEEK = "EgIIAw%3D%3D"

# android/ios/tv clients avoid the throttling that blocks the default web client
# when many videos are fetched in a row.
COMMON_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extractor_args": {"youtube": {"player_client": ["android", "ios", "tv"]}},
    "socket_timeout": 30,
}

HANGUL = range(0xAC00, 0xD7A4)


def target_date():
    """Yesterday's calendar date in KST, plus its UTC bounds."""
    override = os.environ.get("TARGET_DATE")
    day = (
        dt.date.fromisoformat(override)
        if override
        else (dt.datetime.now(KST) - dt.timedelta(days=1)).date()
    )
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=KST)
    return day, start, start + dt.timedelta(days=1)


def search_candidates(keyword, limit):
    """Flat search: cheap per-result metadata (no exact upload time) for triage.

    Returns None (not []) when the search itself failed, so the caller can tell
    "nothing matched" apart from "the network broke".
    """
    url = f"https://www.youtube.com/results?search_query={quote(keyword)}&sp={SP_THIS_WEEK}"
    opts = dict(COMMON_OPTS, extract_flat=True, playlistend=limit)
    info = None
    for attempt in (1, 2):
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            break
        except Exception as exc:
            print(f"  ! search attempt {attempt} failed for {keyword!r}: {exc}", file=sys.stderr)
            if attempt == 2:
                return None
            time.sleep(5)

    out = []
    for entry in (info or {}).get("entries") or []:
        vid = entry.get("id") or ""
        # Search pages mix in channels and playlists; only 11-char video ids qualify.
        if entry.get("ie_key") != "Youtube" or len(vid) != 11:
            continue
        out.append(
            {
                "id": vid,
                "flat_title": entry.get("title") or "",
                "flat_channel": entry.get("channel") or "",
                "flat_views": entry.get("view_count") or 0,
            }
        )
    return out


def fetch_meta(video_id):
    try:
        with YoutubeDL(COMMON_OPTS) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
    except Exception as exc:
        print(f"  ! meta failed for {video_id}: {exc}", file=sys.stderr)
        return None
    ts = info.get("timestamp")
    if ts is None:
        # upload_date is date-only and timezone-ambiguous; without a real
        # timestamp the calendar date cannot be proven, so drop the candidate.
        return None
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "channel": info.get("uploader") or info.get("channel") or "",
        "channel_id": info.get("channel_id") or "",
        "views": info.get("view_count") or 0,
        "likes": info.get("like_count"),
        "timestamp": ts,
        "description": (info.get("description") or "")[:400],
        "url": f"https://www.youtube.com/watch?v={info.get('id')}",
        "thumbnail": f"https://i.ytimg.com/vi/{info.get('id')}/hqdefault.jpg",
    }


def is_relevant(*parts):
    """Korean food/menu content only.

    The loose version of this filter (any food word anywhere) let through Tokyo
    travel guides and a US local-news piece about Massachusetts restaurants, so
    it also requires Korean text and rejects overseas-travel markers.
    """
    hay = " ".join(p for p in parts if p).lower()
    if CONFIG.get("requireHangul") and not any(ord(c) in HANGUL for c in hay):
        return False
    if any(w.lower() in hay for w in CONFIG.get("excludeWords", [])):
        return False
    return any(w.lower() in hay for w in CONFIG.get("includeWords", []))


def tier_of(title, description=""):
    """Mark actual product launches apart from general food content.

    Both are worth publishing, but a reader scanning for launches should not
    have to guess which is which.
    """
    hay = (title + " " + description).lower()
    if any(w.lower() in hay for w in CONFIG.get("coreWords", [])):
        return "신메뉴·신상"
    return "푸드 콘텐츠"


def brand_of(title):
    for b in CONFIG.get("brandTags", []):
        if b.lower() in title.lower():
            return b
    return None


def collect():
    day, start, end = target_date()
    start_ts, end_ts = start.timestamp(), end.timestamp()
    threshold = CONFIG.get("viewThreshold", 1000)
    top_n = CONFIG.get("topN", 10)
    print(f"target date (KST): {day}  window {start.isoformat()} .. {end.isoformat()}")

    seen, pool, failed = set(), [], []
    for kw in CONFIG["keywords"]:
        found = search_candidates(kw, CONFIG.get("perKeyword", 30))
        if found is None:
            failed.append(kw)
            print(f"  flat {kw!r}: FAILED")
            continue
        print(f"  flat {kw!r}: {len(found)}")
        for entry in found:
            if entry["id"] not in seen:
                seen.add(entry["id"])
                pool.append(entry)

    # A run that lost keywords to network errors would quietly publish a thinner
    # report than the data warrants. Fail loudly instead, so the workflow stops
    # and yesterday's page stays up.
    if len(failed) > len(CONFIG["keywords"]) // 2:
        raise SystemExit(
            f"aborting: {len(failed)}/{len(CONFIG['keywords'])} keyword searches failed "
            f"({', '.join(failed)}). Nothing was written."
        )
    if failed:
        print(f"::warning::{len(failed)} keyword search(es) failed: {', '.join(failed)}")

    # Triage on the free flat metadata so the expensive per-video fetches are
    # spent on plausible candidates only. These numbers are never published —
    # the exact view count always comes from the per-video fetch below.
    rejected = {"date": 0, "views": 0, "relevance": 0, "unverifiable": 0}
    triaged = []
    for entry in pool:
        if entry["flat_views"] and entry["flat_views"] < threshold:
            rejected["views"] += 1
            continue
        if not is_relevant(entry["flat_title"], entry["flat_channel"]):
            rejected["relevance"] += 1
            continue
        triaged.append(entry)

    # Highest view count first: once enough are confirmed, every remaining
    # candidate has fewer views and cannot displace them, so we can stop early.
    triaged.sort(key=lambda e: e["flat_views"], reverse=True)
    triaged = triaged[: CONFIG.get("maxCandidates", 120)]
    print(f"pool {len(pool)} -> triaged {len(triaged)} (fetching exact upload time for each)")

    kept, fetch_attempts = [], 0
    for i, entry in enumerate(triaged, 1):
        # Keep collecting past top_n so the per-channel cap still has choices.
        if len(kept) >= top_n * 2:
            print(f"  early stop after {i - 1} fetches ({len(kept)} qualified)")
            break
        fetch_attempts += 1
        meta = fetch_meta(entry["id"])
        if meta is None:
            rejected["unverifiable"] += 1
            continue
        if not (start_ts <= meta["timestamp"] < end_ts):
            rejected["date"] += 1
            continue
        if meta["views"] < threshold:
            rejected["views"] += 1
            continue
        # Re-check relevance against the video's real metadata. YouTube serves
        # auto-translated titles on the search page, so a US news clip can look
        # Korean during triage and arrive here with its original English title.
        if not is_relevant(meta["title"], meta["channel"], meta["description"]):
            rejected["relevance"] += 1
            continue
        meta["brand"] = brand_of(meta["title"])
        meta["tier"] = tier_of(meta["title"], meta["description"])
        kept.append(meta)

    kept.sort(key=lambda m: m["views"], reverse=True)

    # Cap per channel so one prolific channel cannot take over the whole board.
    cap, counts, final = CONFIG.get("perChannel", 2), {}, []
    for item in kept:
        cid = item["channel_id"] or item["channel"]
        if counts.get(cid, 0) >= cap:
            continue
        counts[cid] = counts.get(cid, 0) + 1
        final.append(item)

    final = final[:top_n]
    print(f"qualified {len(kept)} -> published {len(final)}  rejected={rejected}")

    return {
        "date": day.isoformat(),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "keywords": CONFIG["keywords"],
        "viewThreshold": threshold,
        "candidateCount": len(pool),
        "qualifiedCount": len(kept),
        "fetchAttempts": fetch_attempts,
        "failedKeywords": failed,
        "rejected": rejected,
        "items": final,
    }


def main():
    report = collect()
    (ROOT / "data").mkdir(exist_ok=True)
    out = ROOT / "data" / f"{report['date']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
