#!/usr/bin/env python3
"""Quality gate for a collected report, before it is allowed to publish.

The checks are the four review perspectives that were applied to this report by
hand, turned into something that can run every morning without a human:

  감사역 (data integrity)   — every published number must be verifiable, and the
                              filters the report claims are re-applied here to
                              the finished items rather than trusted
  엔지니어 (reproducibility) — the run itself must be complete, not a partial
                              collection that silently looks like a quiet day
  마케팅 (usefulness)        — a board of one channel's uploads is not a trend
  경영진 (decision value)    — if almost nothing is an actual product launch,
                              say so on the page instead of implying otherwise

HARD failures block publication: the previous day's page stays up, which is
better than replacing it with something wrong. SOFT failures publish with a
visible warning, because a genuinely quiet day is a real answer.

Usage: python scripts/verify.py [data/<date>.json]
"""

import json
import os
import sys
import datetime as dt
from collections import Counter
from pathlib import Path

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
HANGUL = range(0xAC00, 0xD7A4)

REQUIRED_FIELDS = ("id", "title", "channel", "views", "timestamp", "url")


def target_data_file():
    """The file for the date this run is about — the same date build.py used.

    Picking the alphabetically last file instead looks right every normal
    morning (the newest date is the newest file) and is wrong the moment a past
    date is rebuilt: collecting 09-12 while 09-13 exists verified 09-13 and left
    09-12 unchecked and unpublished. All three scripts derive the date the same
    way so they cannot disagree.
    """
    override = os.environ.get("TARGET_DATE", "").strip()
    if override:
        try:
            day = dt.date.fromisoformat(override)
        except ValueError:
            sys.exit(f"TARGET_DATE={override!r} 형식이 잘못됐습니다 — YYYY-MM-DD 로 입력하세요")
    else:
        day = (dt.datetime.now(KST) - dt.timedelta(days=1)).date()
    path = ROOT / "data" / f"{day.isoformat()}.json"
    if not path.exists():
        sys.exit(f"{path.name} not found — run scripts/build.py first")
    return path


def filter_violations(item):
    """Re-apply the content filters to an item that is already in the report.

    build.py applies these while collecting, so repeating them here looks
    redundant — but the collector grading its own output is not a gate. If
    is_relevant() regresses, or a config change silently fails to take effect,
    only an independent pass over the finished report catches it. The two
    SpongeBob recaps and the cat-food clip that reached the live page would all
    have been stopped here.
    """
    hay = " ".join(
        str(item.get(f) or "") for f in ("title", "channel", "description")
    ).lower()
    out = []
    if CONFIG.get("requireHangul") and not any(ord(c) in HANGUL for c in hay):
        out.append("한글 없음")
    hits = [w for w in CONFIG.get("excludeWords", []) if w.lower() in hay]
    if hits:
        out.append(f"제외어({', '.join(hits[:3])})")
    ch = (item.get("channel") or "").lower()
    bad = [c for c in CONFIG.get("excludeChannels", []) if c.lower() in ch]
    if bad:
        out.append(f"제외채널({', '.join(bad)})")
    if not any(w.lower() in hay for w in CONFIG.get("includeWords", [])):
        out.append("포함어 없음")
    return out


def check(report):
    hard, soft = [], []
    items = report.get("items", [])
    threshold = report.get("viewThreshold", CONFIG.get("viewThreshold", 1000))
    day = dt.date.fromisoformat(report["date"])
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=KST).timestamp()
    end = start + 86400

    # --- 감사역: every published number must be verifiable and within the claimed filters
    for item in items:
        missing = [f for f in REQUIRED_FIELDS if item.get(f) in (None, "")]
        if missing:
            hard.append(f"[감사역] '{item.get('id', '?')}' 필수 항목 누락: {', '.join(missing)}")
        ts = item.get("timestamp")
        if ts is not None and not (start <= ts < end):
            actual = dt.datetime.fromtimestamp(ts, KST).date().isoformat()
            hard.append(f"[감사역] '{item['id']}' 업로드일 불일치: {actual} ≠ {report['date']}")
        if isinstance(item.get("views"), int) and item["views"] < threshold:
            hard.append(f"[감사역] '{item['id']}' 조회수 {item['views']} < 기준 {threshold}")
        bad = filter_violations(item)
        if bad:
            hard.append(
                f"[감사역] '{item.get('id', '?')}' 필터 위반: {', '.join(bad)} "
                f"— {(item.get('title') or '')[:36]}"
            )

    ids = [i.get("id") for i in items]
    dupes = [vid for vid, n in Counter(ids).items() if n > 1]
    if dupes:
        hard.append(f"[감사역] 중복 영상: {', '.join(dupes)}")

    # --- 엔지니어: the run must be complete enough to trust
    rejected = report.get("rejected", {})
    unverifiable = rejected.get("unverifiable", 0)
    # Only per-video fetches can fail this way; triage rejections never reached
    # the network, so counting them would dilute the ratio this check exists for.
    attempted = report.get("fetchAttempts") or (unverifiable + len(items))
    if attempted and unverifiable / attempted > 0.2:
        hard.append(
            f"[엔지니어] 확인 불가 비율 {unverifiable}/{attempted} "
            f"({unverifiable / attempted:.0%}) — 수집이 불완전합니다"
        )
    if not report.get("candidateCount"):
        hard.append("[엔지니어] 후보를 한 건도 모으지 못했습니다")

    # --- 마케팅: a usable board, not one channel's feed
    cap = CONFIG.get("perChannel", 2)
    per_channel = Counter(i.get("channel") for i in items)
    over = [c for c, n in per_channel.items() if n > cap]
    if over:
        hard.append(f"[마케팅] 채널당 상한({cap}) 초과: {', '.join(over)}")

    if len(items) < 5:
        soft.append(f"[마케팅] 게재 {len(items)}건 — 평소보다 적습니다(기준 5건)")

    # --- 경영진: is this actually about new menus?
    launches = [i for i in items if i.get("tier") == "신메뉴·신상"]
    ratio = len(launches) / len(items) if items else 0
    if items and ratio < 0.3:
        soft.append(
            f"[경영진] 실제 신메뉴·신상은 {len(launches)}/{len(items)}건({ratio:.0%}) — "
            "나머지는 일반 푸드 콘텐츠입니다"
        )
    if items and not any(i.get("brand") for i in items):
        soft.append("[경영진] 등록된 브랜드가 언급된 항목이 없습니다")

    # --- Instagram, when a manual run collected it. Its metric is 좋아요, and a
    # fallback post must carry its own real date so it is never read as the
    # target day's post.
    ig = report.get("instagram") or {}
    for item in ig.get("exact") or []:
        if item.get("likes") in (None, ""):
            hard.append(f"[감사역] 인스타 '{item.get('url', '?')}' 좋아요 수 없음")
        if "views" in item:
            hard.append(f"[감사역] 인스타 '{item.get('url', '?')}' 조회수 필드 사용 — 좋아요만 허용")
    for item in ig.get("fallback") or []:
        if not item.get("realDate"):
            hard.append(
                f"[감사역] 인스타 대체 게시물 '{item.get('url', '?')}' 실제 날짜 없음 "
                "— 기준일 게시물로 오인될 수 있습니다"
            )
        elif item["realDate"] == report["date"]:
            hard.append(
                f"[감사역] 인스타 '{item.get('url', '?')}'는 기준일 게시물인데 대체 항목으로 분류됨"
            )

    return hard, soft


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else target_data_file()
    report = json.loads(path.read_text(encoding="utf-8"))
    hard, soft = check(report)

    result = {
        "date": report["date"],
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "passed": not hard,
        "hard": hard,
        "soft": soft,
        "itemCount": len(report.get("items", [])),
    }
    out = path.with_suffix(".verify.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"검증 대상: {path.name} ({result['itemCount']}건)")
    for line in hard:
        print(f"  FAIL {line}")
    for line in soft:
        print(f"  WARN {line}")
    if not hard and not soft:
        print("  통과 — 지적 사항 없음")

    if hard:
        print(f"\n검증 실패 {len(hard)}건 — 발행하지 않습니다. 기존 리포트가 그대로 유지됩니다.")
        sys.exit(1)
    print(f"\n검증 통과 (경고 {len(soft)}건)")


if __name__ == "__main__":
    main()
