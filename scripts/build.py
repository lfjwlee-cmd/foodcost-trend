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
import re
import sys
import time
import datetime as dt
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# Korean output must not depend on the console codepage (cp949 on Windows
# raises UnicodeEncodeError on an em dash and kills the run).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()


def _lazy_ytdlp():
    """Imported only on the yt-dlp path so the API path needs no dependency."""
    from yt_dlp import YoutubeDL

    return YoutubeDL


def parse_target_date():
    """The date this run is about: TARGET_DATE if set, else KST-yesterday.

    All three scripts resolve the date this same way so they cannot disagree
    about which day is being built, verified and rendered.
    """
    override = (os.environ.get("TARGET_DATE") or "").strip()
    if not override:
        return (dt.datetime.now(KST) - dt.timedelta(days=1)).date()
    try:
        return dt.date.fromisoformat(override)
    except ValueError:
        sys.exit(f"TARGET_DATE={override!r} 형식이 잘못됐습니다 — YYYY-MM-DD 로 입력하세요")


def target_date():
    """Target date plus its KST day bounds."""
    day = parse_target_date()
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=KST)
    return day, start, start + dt.timedelta(days=1)


def search_candidates(keyword, limit):
    """Flat search: cheap per-result metadata (no exact upload time) for triage.

    Returns None (not []) when the search itself failed, so the caller can tell
    "nothing matched" apart from "the network broke".
    """
    YoutubeDL = _lazy_ytdlp()
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
    YoutubeDL = _lazy_ytdlp()
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


def is_blocked_channel(channel):
    ch = (channel or "").lower()
    return any(c.lower() in ch for c in CONFIG.get("excludeChannels", []))


def is_relevant(*parts):
    """Korean food/menu content about real, buyable products.

    Every exclusion here comes from something that actually got published and
    should not have:
      - a Tokyo travel guide and a US news piece about Massachusetts
        restaurants (fixed by requiring Korean text and dropping travel markers)
      - two SpongeBob episode recaps that ranked 4th and 10th, because
        "집게리아 신메뉴" satisfies a food-word filter perfectly well
    Fiction is the tricky class: it uses menu vocabulary correctly, so only the
    subject matter separates it. Word-matching alone will keep leaking, which is
    why `excludeChannels` exists — once a channel produces a false positive,
    block the channel rather than guessing at its next title.
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
    """The registered brand a title actually mentions, or None.

    Plain substring matching is right for Hangul, which has no word boundaries,
    and wrong for short ASCII tags: "CU" matches inside "cup", "cute" and
    "culture", which are not rare in Korean titles that mix in English. That is
    the same class of false positive that "냥" inside "그냥" would cause, so
    ASCII tags require word boundaries.
    """
    for b in CONFIG.get("brandTags", []):
        if b.isascii():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(b)}(?![A-Za-z0-9])", title, re.I):
                return b
        elif b.lower() in title.lower():
            return b
    return None


def api_get(endpoint, params):
    """One YouTube Data API call. Raises on failure — the caller decides."""
    qs = urlencode(dict(params, key=API_KEY))
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_api():
    """Collect via the official Data API.

    Used on GitHub Actions, where yt-dlp's per-video requests are answered with
    "Sign in to confirm you're not a bot" from datacenter IPs (verified: 40/40
    blocked). The API also filters by publish time server-side, so nearly every
    result is already inside the target day.

    Quota: search.list costs 100 units per keyword, videos.list 1 per call —
    about 610 of the free 10,000/day for the default 6 keywords.
    """
    day, start, end = target_date()
    threshold = CONFIG.get("viewThreshold", 1000)
    top_n = CONFIG.get("topN", 10)
    print(f"engine: YouTube Data API | target date (KST): {day}")

    seen, ids, failed = set(), [], []
    for kw in CONFIG["keywords"]:
        try:
            data = api_get(
                "search",
                {
                    "part": "snippet",
                    "q": kw,
                    "type": "video",
                    "order": "viewCount",
                    "regionCode": CONFIG.get("regionCode", "KR"),
                    "relevanceLanguage": CONFIG.get("relevanceLanguage", "ko"),
                    "publishedAfter": start.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "publishedBefore": end.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "maxResults": 50,
                },
            )
        except Exception as exc:
            failed.append(kw)
            print(f"  search {kw!r}: FAILED ({exc})", file=sys.stderr)
            continue
        found = [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        print(f"  search {kw!r}: {len(found)}")
        for vid in found:
            if vid not in seen:
                seen.add(vid)
                ids.append(vid)

    if len(failed) > len(CONFIG["keywords"]) // 2:
        raise SystemExit(
            f"aborting: {len(failed)}/{len(CONFIG['keywords'])} searches failed "
            f"({', '.join(failed)}). Nothing was written."
        )

    # videos.list carries the exact publishedAt and viewCount; search snippets do not.
    rejected = {"date": 0, "views": 0, "relevance": 0, "unverifiable": 0}
    kept, attempts = [], 0
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        attempts += len(batch)
        try:
            data = api_get("videos", {"part": "snippet,statistics", "id": ",".join(batch)})
        except Exception as exc:
            rejected["unverifiable"] += len(batch)
            print(f"  videos.list batch failed: {exc}", file=sys.stderr)
            continue
        returned = {it["id"] for it in data.get("items", [])}
        rejected["unverifiable"] += len(set(batch) - returned)
        for it in data.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            ts = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).timestamp()
            # Re-check the window ourselves rather than trusting the query alone.
            if not (start.timestamp() <= ts < end.timestamp()):
                rejected["date"] += 1
                continue
            views = int(st.get("viewCount", 0))
            if views < threshold:
                rejected["views"] += 1
                continue
            desc = (sn.get("description") or "")[:400]
            if is_blocked_channel(sn.get("channelTitle", "")) or not is_relevant(
                sn.get("title", ""), sn.get("channelTitle", ""), desc
            ):
                rejected["relevance"] += 1
                continue
            kept.append(
                {
                    "id": it["id"],
                    "title": sn.get("title", ""),
                    "channel": sn.get("channelTitle", ""),
                    "channel_id": sn.get("channelId", ""),
                    "views": views,
                    "likes": int(st["likeCount"]) if "likeCount" in st else None,
                    "timestamp": ts,
                    "description": desc,
                    "url": f"https://www.youtube.com/watch?v={it['id']}",
                    "thumbnail": f"https://i.ytimg.com/vi/{it['id']}/hqdefault.jpg",
                    "brand": brand_of(sn.get("title", "")),
                    "tier": tier_of(sn.get("title", ""), desc),
                }
            )

    kept.sort(key=lambda m: m["views"], reverse=True)
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
        "engine": "YouTube Data API",
        "keywords": CONFIG["keywords"],
        "viewThreshold": threshold,
        "candidateCount": len(ids),
        "qualifiedCount": len(kept),
        "fetchAttempts": attempts,
        "failedKeywords": failed,
        "rejected": rejected,
        "items": final,
    }


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

    cap = CONFIG.get("perChannel", 2)
    kept, fetch_attempts, cap_counts = [], 0, {}
    for i, entry in enumerate(triaged, 1):
        # Keep collecting past top_n so the per-channel cap still has choices.
        # Count only what survives the cap: 20 videos from one prolific channel
        # collapse to 2 afterwards, and stopping on the raw count would publish
        # a near-empty board that looks like a quiet day.
        eligible = sum(min(n, cap) for n in cap_counts.values())
        if eligible >= top_n * 2:
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
        if is_blocked_channel(meta["channel"]) or not is_relevant(
            meta["title"], meta["channel"], meta["description"]
        ):
            rejected["relevance"] += 1
            continue
        meta["brand"] = brand_of(meta["title"])
        meta["tier"] = tier_of(meta["title"], meta["description"])
        kept.append(meta)
        cid = meta["channel_id"] or meta["channel"]
        cap_counts[cid] = cap_counts.get(cid, 0) + 1

    kept.sort(key=lambda m: m["views"], reverse=True)

    # Cap per channel so one prolific channel cannot take over the whole board.
    counts, final = {}, []
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
        "engine": "yt-dlp",
        "candidateCount": len(pool),
        "qualifiedCount": len(kept),
        "fetchAttempts": fetch_attempts,
        "failedKeywords": failed,
        "rejected": rejected,
        "items": final,
    }


def main():
    # With a key, use the official API (the only path that works from CI).
    # Without one, fall back to yt-dlp, which works fine from a home network.
    report = collect_api() if API_KEY else collect()
    (ROOT / "data").mkdir(exist_ok=True)
    out = ROOT / "data" / f"{report['date']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
