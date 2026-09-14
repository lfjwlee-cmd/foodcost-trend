"""Local self-test for the Naver section (no Naver keys needed).

Checks three things the daily run depends on:
  1. unconfigured  -> section is skipped cleanly and the page says so
  2. with data     -> counts render as counts, never as views
  3. bad data      -> the verify gate blocks it
"""

import copy
import json
import re
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

DATA = ROOT / "data" / "2026-09-13.json"
if not DATA.exists():
    url = "https://raw.githubusercontent.com/lfjwlee-cmd/foodcost-trend/main/data/2026-09-13.json"
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    print("fetched real report data from the repo")

base = json.loads(DATA.read_text(encoding="utf-8"))

print("\n=== 1. unconfigured Naver ===")
import naver  # noqa: E402

print("configured():", naver.configured())
print("collect() ->", naver.collect(base["date"]))

print("\n=== 2. render with mock Naver data ===")
mock = copy.deepcopy(base)
mock["naver"] = {
    "date": base["date"],
    "metric": "언급 건수",
    "note": "언급 건수입니다.",
    "corpora": ["블로그", "카페"],
    "failedTerms": [],
    "terms": [
        {"term": "CU 신상", "count": 41, "capped": False,
         "samples": [{"title": "CU <b>신상</b> 털기", "link": "https://blog.naver.com/x/1", "source": "블로그"}]},
        {"term": "맘스터치 신메뉴", "count": 17, "capped": False,
         "samples": [{"title": "맘스터치 스모키스매쉬 후기", "link": "https://blog.naver.com/x/2", "source": "블로그"}]},
        {"term": "스타벅스 신메뉴", "count": 100, "capped": True, "samples": []},
        {"term": "엽떡 신메뉴", "count": 0, "capped": False, "samples": []},
    ],
}
import render  # noqa: E402

html = render.render(mock, {"passed": True, "soft": [], "checkedAt": "2026-09-14T00:00:00+00:00"})
checks = {
    "네이버 섹션 존재": "블로그·카페 언급" in html,
    "언급 건수 표기": "41건" in html,
    "capped 100+ 표기": "100건+" in html,
    "0건은 숨김": "엽떡 신메뉴" not in html,
    "조회수와 혼동 경고문": "조회수와 같은 줄에 놓고 비교할 수 없습니다" in html,
    # Assert on shape, not on a specific number: view counts are live and move
    # between runs (108,586 -> 108,965 while writing this test).
    "유튜브 섹션 유지": '<div class="grid">' in html and "▶ 유튜브" in html,
    "유튜브 카드 10건": html.count('class="card ') == len(mock["items"]),
    "조회수 표기 형식": bool(re.search(r'class="views">조회수 [\d,]+회', html)),
}
for k, v in checks.items():
    print(("OK  " if v else "FAIL") + " | " + k)

print("\n=== 3. verify gate, bad Naver data ===")
cases = {
    "지표를 조회수로 바꿈": lambda d: d["naver"].update({"metric": "조회수"}),
    "집계일 불일치": lambda d: d["naver"].update({"date": "2026-01-01"}),
    "count가 문자열": lambda d: d["naver"]["terms"][0].update({"count": "많음"}),
    "views 필드 주입": lambda d: d["naver"]["terms"][0].update({"views": 9999}),
    "(대조군) 정상": lambda d: None,
}
tmp = ROOT / "data" / "_selftest.json"
for name, mutate in cases.items():
    d = copy.deepcopy(mock)
    mutate(d)
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify.py"), str(tmp)],
                       capture_output=True, text=True, encoding="utf-8")
    print(("BLOCKED" if r.returncode else "PASSED ") + " | " + name)
tmp.unlink(missing_ok=True)
(ROOT / "data" / "_selftest.verify.json").unlink(missing_ok=True)
