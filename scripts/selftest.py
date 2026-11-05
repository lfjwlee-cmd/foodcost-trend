#!/usr/bin/env python3
"""Prove the rules behave identically on any machine, without touching YouTube.

Why this exists: "does someone else get the same result?" has two different
answers, and mixing them up is the trap.

  Collection is NOT reproducible. It reads a live source. The same video gains
  views between one run and the next, and the keyless engine (yt-dlp scraping
  search) sees a different candidate pool than the API engine. Two people
  running on the same date will get overlapping — not identical — top-10 lists,
  and that is a property of the data, not a bug in this code.

  Everything after collection IS reproducible. Given the same data file, the
  filters, the quality gate and the renderer must reach the same verdict on
  every machine, in every timezone, with any console encoding.

This file tests the second half against fixed fixtures, so anyone who clones
the repo can run one command and see whether their copy behaves like the
reference. A failure here means the rules drifted; a different top-10 does not.

Usage: python scripts/selftest.py   (exit 0 = all rules behave as documented)
"""

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load("build")
verify = _load("verify")
rollup = _load("rollup")
naver = _load("naver")

BASE = json.loads((ROOT / "tests" / "fixture.json").read_text(encoding="utf-8"))
results = []


def case(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail and not ok else ''}")


def mutate(fn):
    """A copy of the clean fixture with one thing wrong."""
    report = copy.deepcopy(BASE)
    fn(report)
    return report


def hard_of(report):
    return verify.check(report)[0]


print("1. 깨끗한 데이터는 통과해야 한다")
hard, soft = verify.check(copy.deepcopy(BASE))
case("정상 리포트 하드 실패 0건", not hard, "; ".join(hard))

print("\n2. 알려진 오탐은 게이트가 잡아야 한다 (실제로 발행됐던 것들)")
FAKES = [
    ("만화 — 스폰지밥", {"title": "스폰지밥이 만든 신메뉴", "channel": "별밤냐옹",
                     "description": "시즌7 에피소드150a 게살버거"}),
    ("반려동물 — 고양이 사료", {"title": "내일은 신메뉴로 먹자", "channel": "테스트냥",
                          "description": "고양이 사료 급여 후기 집사"}),
    ("영어 뉴스", {"title": "New menu at a Boston restaurant", "channel": "WCVB",
                "description": "A new restaurant menu"}),
    ("여행 콘텐츠", {"title": "도쿄 디저트 맛집 투어", "channel": "여행채널",
                 "description": "오사카 여행 먹거리"}),
]
for label, patch in FAKES:
    item = dict(BASE["items"][0], **patch, id="fake0000000")
    case(f"차단: {label}", bool(verify.filter_violations(item)))

print("\n3. 숫자·구조 위반은 하드 실패여야 한다")
def set_views(r): r["items"][0]["views"] = 999
case("조회수 하한 미달", any("조회수" in h for h in hard_of(mutate(set_views))))

def set_date(r): r["items"][0]["timestamp"] = 1700000000
case("업로드일 불일치", any("업로드일" in h for h in hard_of(mutate(set_date))))

def dupe(r): r["items"].append(copy.deepcopy(r["items"][0]))
case("중복 영상", any("중복" in h for h in hard_of(mutate(dupe))))

def over_cap(r):
    extra = copy.deepcopy(r["items"][0])
    extra.update(id="ddddddddddd", title="신메뉴 편의점 디저트 3번째")
    r["items"].append(extra)
case("채널당 상한 초과", any("상한" in h for h in hard_of(mutate(over_cap))))

def missing(r): r["items"][0]["url"] = ""
case("필수 항목 누락", any("필수 항목" in h for h in hard_of(mutate(missing))))

def unverifiable(r):
    r["rejected"]["unverifiable"] = 10
    r["fetchAttempts"] = 12
case("확인 불가 비율 초과", any("확인 불가" in h for h in hard_of(mutate(unverifiable))))

def ig_views(r):
    r["instagram"] = {"exact": [{"url": "x", "likes": 10, "views": 500}]}
case("인스타 조회수 필드 거부(좋아요만)", any("조회수 필드" in h for h in hard_of(mutate(ig_views))))

print("\n4. 분류 규칙")
case("브랜드 — 정확히 언급하면 인식", build.brand_of("CU 신상 김밥") == "CU")
case("브랜드 — cup/cute 안의 CU는 무시", build.brand_of("아이스 free cup cute 신메뉴") is None)
case("등급 — 출시어가 있으면 신메뉴", build.tier_of("신메뉴 출시") == "신메뉴·신상")
case("등급 — 없으면 푸드 콘텐츠", build.tier_of("떡볶이 먹방") == "푸드 콘텐츠")

case("브랜드 — 약칭도 정식명으로", build.brand_of("투썸 신메뉴 밤생크림") == "투썸플레이스")
case("브랜드 — 긴 표기가 먼저", build.brand_of("GS25 신상 김밥") == "GS25")
case("브랜드 — 짧은 조각은 안 넣는다(메가톤)", build.brand_of("메가톤급 신메뉴") is None)
case("브랜드 — 한 제목의 여러 브랜드를 모두",
     build.brands_in("GS편의점 신상 두찜 실비김치") == ["GS25", "두찜"])

print("\n5. 짧은 영상 판정")
case("길이 — ISO8601 해석", build.parse_duration("PT1M23S") == 83)
case("길이 — 형식이 깨지면 None", build.parse_duration("garbage") is None)
case("숏폼 — 기준 이하", build.is_short(45, "신상 리뷰") is True)
case("숏폼 — #shorts 는 길이를 이긴다", build.is_short(200, "신상 #shorts") is True)
case("숏폼 — 길면 아니다", build.is_short(200, "일반 먹방") is False)
case("숏폼 — 길이를 모르면 단정하지 않는다", build.is_short(None, "신상 리뷰") is False)

print("\n6. 주간 묶음 규칙")


def _vid(n, title, channel, day, views=1000):
    return {"id": f"v{n}", "title": title, "channel": channel, "day": day,
            "views": views, "url": "u", "timestamp": 0}


one_channel = [
    _vid(1, "샤브올데이 가을 신메뉴 바다편 15초", "샤브올데이", "2026-09-18"),
    _vid(2, "샤브올데이 가을 신메뉴 바다편 60초", "샤브올데이", "2026-09-18"),
]
ev, _ = rollup.group_events(one_channel)
case("한 채널이 두 번 올린 건 사건이 아니다", ev == [])

two_channels = [
    _vid(1, "엽떡 더착한맛 먹어봄", "채널가", "2026-09-16"),
    _vid(2, "엽떡 더 착한 맛 솔직리뷰", "채널나", "2026-09-17"),
]
ev, solo = rollup.group_events(two_channels)
case("띄어쓰기가 달라도 같은 메뉴", len(ev) == 1 and ev[0]["count"] == 2)
case("브랜드가 과반이면 라벨", ev and ev[0]["brand"] == "엽떡")

mixed = [
    _vid(1, "뚜레쥬르 하트티라미수 신상", "채널가", "2026-09-17"),
    _vid(2, "밤 티라미수 신메뉴", "채널나", "2026-09-19"),
]
ev, _ = rollup.group_events(mixed)
case("브랜드가 과반이 아니면 라벨 없음", ev and ev[0]["brand"] is None)

roundup = [
    _vid(1, "엽떡 더착한맛", "채널가", "2026-09-16"),
    _vid(2, "엽떡 더착한맛 리뷰", "채널나", "2026-09-17"),
    _vid(3, "엽떡 더착한맛 쇼콜라 말차하임 신상털이", "채널다", "2026-09-20"),
    _vid(4, "쇼콜라 말차하임 디저트", "채널라", "2026-09-21"),
]
ev, _ = rollup.group_events(roundup)
case("모아보기 영상은 한 사건에만 들어간다",
     sum(e["count"] for e in ev) <= len(roundup))

react = [
    dict(_vid(1, "엽떡 더착한맛", "채널가", "2026-09-16", views=1000), likes=50),
    dict(_vid(2, "엽떡 더착한맛 리뷰", "채널나", "2026-09-17", views=1000), likes=30),
]
ev, _ = rollup.group_events(react)
case("반응률 — 좋아요를 합산한다", bool(ev) and ev[0]["likes"] == 80)

no_likes = [
    dict(_vid(1, "엽떡 더착한맛", "채널가", "2026-09-16"), likes=None),
    dict(_vid(2, "엽떡 더착한맛 리뷰", "채널나", "2026-09-17"), likes=None),
]
ev2, _ = rollup.group_events(no_likes)
case("반응률 — 좋아요가 없어도 터지지 않는다", bool(ev2) and ev2[0]["likes"] == 0)

print("\n7. 네이버 언급량 집계 (네트워크 없이)")

PAGES = {
    1: {"total": 9999, "items": [
        {"postdate": "20261101"}, {"postdate": "20261029"},
        {"postdate": "20261026"}, {"postdate": "20261020"},
    ]},
}
r = naver.count_in_window("q", "2026-10-26", "2026-11-01",
                          fetch=lambda q, start=1: PAGES[1], max_pages=1)
case("기간 안의 글만 센다", r["count"] == 3)
case("기간보다 오래된 글에서 멈춘다", r["scanned"] == 4)
case("끝까지 안 갔으면 잘린 표시 없음", r["capped"] is False)

full = {"total": 9999, "items": [{"postdate": "20261101"}] * naver.PER_PAGE}
r2 = naver.count_in_window("q", "2026-10-26", "2026-11-01",
                           fetch=lambda q, start=1: full, max_pages=2)
case("페이지 한도에서 잘리면 표시한다", r2["capped"] is True)

print("\n8. 같은 입력 = 같은 판정 (재현성)")
a = verify.check(copy.deepcopy(BASE))
b = verify.check(copy.deepcopy(BASE))
case("검증을 두 번 돌려도 동일", a == b)
g1, s1 = rollup.group_events(copy.deepcopy(roundup))
g2, s2 = rollup.group_events(copy.deepcopy(roundup))
case("주간 묶음을 두 번 돌려도 동일", (g1, s1) == (g2, s2))

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
if failed:
    print("실패: " + ", ".join(failed))
    sys.exit(1)
print("규칙 엔진이 기준과 동일하게 동작합니다.")
