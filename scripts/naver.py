#!/usr/bin/env python3
"""네이버 블로그 언급량 — 유튜브에서 뜬 메뉴가 바깥으로 번졌는지 보는 축.

이 저장소는 2026-09-14에 네이버 섹션을 한 번 들어냈다(커밋 4fb557b). 그때
이유는 타당했다 — 네이버가 주는 건 조회수가 아니라 문서 수인데, 조회수로
줄 세운 카드 옆에 놓으니 비교가 되지 않았다.

지금 다시 넣는 이유는 자리가 달라져서다. 주간 롤업은 랭킹이 아니라 "이게
흐름인가"를 묻는 페이지이고, 거기서는 **다른 종류의 신호**가 필요하다.
유튜브 채널 여섯 곳이 다뤘다는 사실과 같은 기간 블로그에 글이 몇 건 올라왔다는
사실은 서로를 검증한다. 조회수를 세는 소스를 하나 더 붙였다면 잡음만 늘었다.

## 왜 total을 쓰지 않는가

검색 API 응답의 `total`은 **역대 전체** 문서 수다. 기간 필터가 없어서
"이번 주에 몇 건"에 답하지 못한다. 그래서 날짜순으로 받아 창 안에 든 것만
센다. 블로그 항목에는 `postdate`(YYYYMMDD)가 있어 이게 가능하다. 카페
검색에는 날짜 필드가 없어 같은 방법을 쓸 수 없으므로 블로그만 집계한다.

## 한도

무료, 하루 25,000회. 사건 7개 × 최대 3페이지 = 21회로 사실상 무시할 수 있다.

설정: 네이버 개발자센터에서 앱을 등록해 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
환경변수(또는 GitHub Secret)로 넣는다. 없으면 이 모듈은 조용히 비활성이고
주간 페이지는 해당 열을 빼고 그 사실을 적는다.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://openapi.naver.com/v1/search/blog.json"
PER_PAGE = 100          # API maximum
MAX_PAGES = 3           # 300 posts per menu is deep enough to bound a week
TIMEOUT = 10


def credentials():
    """(id, secret), or None when the deploy has not been given any."""
    cid = (os.environ.get("NAVER_CLIENT_ID") or "").strip()
    secret = (os.environ.get("NAVER_CLIENT_SECRET") or "").strip()
    return (cid, secret) if cid and secret else None


def search(query, start=1, display=PER_PAGE, sort="date"):
    """One API call. Raises on failure — the caller decides whether that is fatal."""
    creds = credentials()
    if not creds:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 없습니다")
    cid, secret = creds
    qs = urllib.parse.urlencode(
        {"query": query, "display": display, "start": start, "sort": sort}
    )
    req = urllib.request.Request(
        f"{ENDPOINT}?{qs}",
        headers={
            "X-Naver-Client-Id": cid,
            "X-Naver-Client-Secret": secret,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def count_in_window(query, first_day, last_day, fetch=search, max_pages=MAX_PAGES):
    """날짜순 결과를 훑어 [first_day, last_day] 안의 블로그 글 수를 센다.

    `fetch` 를 갈아끼울 수 있게 둔 건 테스트 때문이다. 세는 규칙은 네트워크
    없이도 고정 픽스처로 증명할 수 있어야 한다.

    반환값의 `capped` 는 "페이지 한도까지 갔는데 아직 창 안이었다"는 뜻이다 —
    실제 건수는 더 많다. 이걸 구분하지 않으면 300 에서 잘린 값이 정확한 수처럼
    읽힌다.
    """
    lo = dt.date.fromisoformat(first_day)
    hi = dt.date.fromisoformat(last_day)
    count = scanned = 0
    total = None
    capped = False
    for page in range(max_pages):
        data = fetch(query, start=page * PER_PAGE + 1)
        if total is None:
            total = data.get("total")
        items = data.get("items") or []
        if not items:
            break
        reached_past = False
        for it in items:
            raw = (it.get("postdate") or "").strip()
            if len(raw) != 8 or not raw.isdigit():
                continue
            scanned += 1
            day = dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            if day < lo:
                # Sorted newest first, so everything after this is older too.
                reached_past = True
                break
            if day <= hi:
                count += 1
        if reached_past or len(items) < PER_PAGE:
            break
    else:
        capped = True
    return {"query": query, "count": count, "capped": capped, "scanned": scanned, "total": total}


def mentions(queries, first_day, last_day):
    """{query: result}. 자격증명이 없거나 호출이 실패하면 None 을 돌려준다.

    주간 롤업은 네이버 없이도 완결된 페이지다. 이 축이 빠졌다고 발행을 멈추면
    곁다리가 본체를 막는 셈이라, 실패는 페이지에 적고 지나간다.
    """
    if not credentials():
        return None
    out = {}
    for q in queries:
        try:
            out[q] = count_in_window(q, first_day, last_day)
        except urllib.error.HTTPError as exc:
            print(f"  ! 네이버 검색 실패({q}): HTTP {exc.code}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"  ! 네이버 검색 실패({q}): {exc}", file=sys.stderr)
            return None
    return out


if __name__ == "__main__":
    # 수동 확인용: python scripts/naver.py "엽떡 더착한맛" 2026-10-26 2026-11-01
    if len(sys.argv) != 4:
        sys.exit("usage: python scripts/naver.py <질의> <시작일> <종료일>")
    if not credentials():
        sys.exit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 를 먼저 설정하세요")
    print(json.dumps(count_in_window(*sys.argv[1:4]), ensure_ascii=False, indent=2))
