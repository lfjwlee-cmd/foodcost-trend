#!/usr/bin/env python3
"""Count yesterday's Naver blog/cafe mentions per brand.

This is deliberately NOT a ranking. Naver's official search API returns only
title, link, description, bloggername and postdate — no view count, no likes,
no comments — so there is no engagement number to sort by. What it can answer
is "how often was this brand written about yesterday", which is a different
signal from YouTube's "how much was this watched": mentions run ahead of views,
so the two belong in separate sections and must never share a ranking.

Needs NAVER_CLIENT_ID / NAVER_CLIENT_SECRET. Without them the caller skips this
section entirely rather than guessing at numbers.

Note: Naver is migrating these keys to NAVER API HUB; Developers Center keys
stop working 2027-06-30.
"""

import json
import os
import sys
import time
import datetime as dt
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
DISPLAY = 100  # API maximum per call


def configured():
    return bool(CLIENT_ID and CLIENT_SECRET)


def _call(corpus, query):
    qs = urlencode({"query": query, "display": DISPLAY, "sort": "date"})
    url = f"https://openapi.naver.com/v1/search/{corpus}.json?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": CLIENT_ID,
            "X-Naver-Client-Secret": CLIENT_SECRET,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _postdate_of(item, corpus):
    """Both blog and cafearticle expose postdate as YYYYMMDD (KST)."""
    raw = (item.get("postdate") or "").strip()
    if len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def count_for(term, target_date):
    """Mentions of `term` posted on target_date, across blog and cafe.

    `capped` means the day's posts filled the API page, so the true number is
    higher than what is reported — shown as "100+" rather than a wrong exact.
    """
    total, capped, samples = 0, False, []
    for corpus in ("blog", "cafearticle"):
        try:
            data = _call(corpus, term)
        except Exception as exc:
            print(f"  ! naver {corpus} {term!r}: {exc}", file=sys.stderr)
            return None
        items = data.get("items", [])
        hits = [it for it in items if _postdate_of(it, corpus) == target_date]
        total += len(hits)
        if len(items) == DISPLAY and len(hits) == DISPLAY:
            capped = True
        for it in hits[:2]:
            samples.append(
                {
                    "title": it.get("title", ""),
                    "link": it.get("link", ""),
                    "source": "블로그" if corpus == "blog" else "카페",
                }
            )
        time.sleep(0.2)  # stay polite to the API
    return {"term": term, "count": total, "capped": capped, "samples": samples[:3]}


def collect(target_date):
    """Returns None when unconfigured, so the report can say so plainly."""
    if not configured():
        print("naver: NAVER_CLIENT_ID/SECRET not set — skipping this section")
        return None

    terms = CONFIG.get("naverWatchTerms") or CONFIG.get("brandTags", [])
    print(f"naver: counting {len(terms)} terms for {target_date}")

    results, failed = [], []
    for term in terms:
        r = count_for(term, target_date)
        if r is None:
            failed.append(term)
            continue
        results.append(r)
        print(f"  {term}: {r['count']}{'+' if r['capped'] else ''}")

    if failed and len(failed) > len(terms) // 2:
        # Half the terms missing would make the comparison between brands
        # meaningless, so report nothing rather than a lopsided table.
        print(f"::warning::naver: {len(failed)}/{len(terms)} terms failed — dropping section")
        return None

    results.sort(key=lambda r: r["count"], reverse=True)
    return {
        "date": target_date,
        "metric": "언급 건수",
        "note": "네이버 검색 API는 조회수·좋아요를 제공하지 않습니다. 이 수치는 언급 건수이며 유튜브 조회수와 비교할 수 없습니다.",
        "corpora": ["블로그", "카페"],
        "failedTerms": failed,
        "terms": results,
    }
