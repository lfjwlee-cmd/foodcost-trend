#!/usr/bin/env python3
"""Render a verified report to docs/ (today's page, per-date archive, index).

Runs only after scripts/verify.py passes, so a failed collection leaves the
previous day's page untouched instead of replacing it with a degraded one.

Usage: python scripts/render.py [data/<date>.json]
"""

import json
import html
import os
import sys
import datetime as dt
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


def esc(s):
    return html.escape(str(s), quote=True)


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def kst_label(iso_date):
    d = dt.date.fromisoformat(iso_date)
    return f"{d.month}월 {d.day}일"


def card(item, rank):
    size = "card--r1" if rank == 1 else "card--r23" if rank <= 3 else ""
    chip = item.get("brand") or item.get("tier") or ""
    dim = "" if (item.get("brand") or item.get("tier") == "신메뉴·신상") else " cat--dim"
    chip_html = f'<span class="cat{dim}">{esc(chip)}</span>' if chip else ""
    return f"""
    <a class="card {size}" href="{esc(item['url'])}" target="_blank" rel="noopener">
      <div class="cover" style="background-image:url('{esc(item['thumbnail'])}')"></div>
      <div class="scrim"></div>
      <span class="rank">{rank}</span>
      <span class="badge">▶ YouTube</span>
      <div class="body">
        {chip_html}
        <p class="title">{esc(item['title'])}</p>
        <div class="meta"><span class="views">조회수 {fmt(item['views'])}회</span><span>· {esc(item['channel'])}</span></div>
      </div>
    </a>"""


STYLE = """
:root{--bg:#faf5ee;--surface:#fff;--surface-2:#f2e9dc;--line:#e6dac8;--ink:#241b12;
--ink-dim:#7a6c58;--accent:#e0451f;--accent-ink:#fff7f0;--gold:#c8860a;--ok:#2f7d55;--warn:#b8761a}
@media (prefers-color-scheme:dark){:root{--bg:#171210;--surface:#211a15;--surface-2:#2a2119;
--line:#3a2d22;--ink:#f4ebdd;--ink-dim:#a99884;--accent:#ff6a3d;--accent-ink:#1a0f08;
--gold:#f3b632;--ok:#63c294;--warn:#f0b44c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Gothic A1',system-ui,sans-serif;
padding:32px clamp(16px,4vw,48px) 56px}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:20px;
padding-bottom:22px;margin-bottom:20px;border-bottom:3px solid var(--ink)}
.eyebrow{font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--accent);
text-transform:uppercase;margin:0 0 6px}
h1{font-family:'Black Han Sans',sans-serif;font-weight:400;font-size:clamp(28px,4.4vw,44px);
line-height:1.1;margin:0}
.head-meta{text-align:right;font-size:13px;color:var(--ink-dim);line-height:1.6}
.head-meta b{color:var(--ink)}
.head-meta a{color:var(--accent);text-decoration:none;font-weight:700}
.verify{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:11px 14px;margin-bottom:20px;
border-radius:10px;background:var(--surface-2);border:1px solid var(--line);font-size:12.5px}
.verify .tag{font-weight:900;padding:3px 10px;border-radius:999px;font-size:11.5px}
.verify .tag.pass{background:var(--ok);color:#fff}
.verify .tag.warn{background:var(--warn);color:#fff}
.verify ul{margin:0;padding-left:18px;color:var(--ink-dim);flex:1 1 100%}
.filter-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px}
.chip{font-size:12.5px;font-weight:700;padding:7px 14px;border-radius:999px;
background:var(--surface-2);border:1px solid var(--line);color:var(--ink-dim)}
.chip b{color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:150px;gap:14px;margin-bottom:30px}
.card{position:relative;border-radius:14px;overflow:hidden;background:var(--surface);
border:1px solid var(--line);color:#fff;display:flex;flex-direction:column;
justify-content:flex-end;text-decoration:none}
.card .cover{position:absolute;inset:0;background-size:cover;background-position:center}
.card .scrim{position:absolute;inset:0;background:linear-gradient(180deg,rgba(20,12,6,0) 28%,
rgba(15,9,5,.55) 60%,rgba(10,6,3,.94) 100%)}
.card .rank{position:absolute;top:10px;left:10px;font-family:'Black Han Sans',sans-serif;
font-size:22px;background:var(--accent);color:var(--accent-ink);min-width:34px;height:34px;
border-radius:8px;display:flex;align-items:center;justify-content:center;z-index:2}
.card .badge{position:absolute;top:10px;right:10px;font-size:11px;font-weight:700;
background:rgba(0,0,0,.55);color:#fff;padding:4px 9px;border-radius:999px;z-index:2}
.card .body{position:relative;z-index:2;padding:12px 14px 13px}
.card .cat{display:inline-block;font-size:10px;font-weight:700;background:var(--gold);
color:#1a0f08;padding:2px 8px;border-radius:999px;margin-bottom:6px}
.card .cat--dim{background:rgba(255,255,255,.22);color:#fff}
.card .badge--ig{background:rgba(182,51,108,.78)}
.card .cover.ph{background:linear-gradient(155deg,#b6336c,#5b2a6b)}
.card .real-date{position:absolute;bottom:10px;right:12px;z-index:3;font-size:10.5px;
font-weight:700;color:#fff;background:rgba(0,0,0,.45);padding:2px 7px;border-radius:999px}
.grid.ig{grid-auto-rows:120px}
h2.section{font-family:'Black Han Sans',sans-serif;font-weight:400;font-size:19px;
margin:0 0 12px;display:flex;align-items:center;gap:9px}
h2.section .n{font-family:'Gothic A1',sans-serif;font-size:12px;font-weight:700;
color:var(--ink-dim);background:var(--surface-2);border:1px solid var(--line);
border-radius:999px;padding:2px 9px}
h3.subsection{font-size:12.5px;font-weight:700;color:var(--ink-dim);margin:18px 0 10px;
letter-spacing:.04em}
.empty code{background:var(--surface-2);border:1px solid var(--line);border-radius:5px;
padding:1px 5px;font-size:12px}
.card .title{font-size:14px;font-weight:700;line-height:1.32;margin:0 0 5px;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .meta{display:flex;gap:7px;font-size:11.5px;color:rgba(255,255,255,.78)}
.card .views{font-variant-numeric:tabular-nums;font-weight:900;color:var(--gold);font-size:13px}
.card--r1{grid-column:span 2;grid-row:span 2}
.card--r1 .title{font-size:19px;-webkit-line-clamp:3}
.card--r1 .views{font-size:18px}
.card--r23{grid-column:span 2}
@media (max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}.card--r1,.card--r23{grid-column:span 2}}
.empty{padding:40px;text-align:center;color:var(--ink-dim);border:1px dashed var(--line);border-radius:14px}
.note{border-top:1px solid var(--line);padding-top:16px;font-size:12.5px;color:var(--ink-dim);line-height:1.75}
.note b{color:var(--ink)}
.note p{margin:10px 0 0}
.note summary{cursor:pointer;font-weight:700;color:var(--ink-dim);list-style:none}
.note summary::-webkit-details-marker{display:none}
.note summary::before{content:"▸ ";color:var(--accent)}
.note[open] summary::before{content:"▾ "}
.note summary:hover{color:var(--ink)}
"""


def ig_card(item, is_fallback):
    """Instagram card. The metric is 좋아요, never 조회수 — Instagram does not
    expose view counts without a login, so a fallback card also shows its own
    real date rather than implying it belongs to the target day."""
    date_badge = (
        f'<span class="real-date">{esc(kst_label(item["realDate"]))} 게시</span>'
        if is_fallback and item.get("realDate")
        else ""
    )
    return f"""
    <a class="card" href="{esc(item['url'])}" target="_blank" rel="noopener">
      <div class="cover ph"></div>
      <div class="scrim"></div>
      <span class="badge badge--ig">📷 Instagram</span>
      <div class="body">
        <span class="cat">{esc(item.get('brand', ''))}</span>
        <p class="title">{esc(item.get('caption', ''))}</p>
        <div class="meta"><span class="views">좋아요 {fmt(item.get('likes'))}개</span></div>
      </div>
      {date_badge}
    </a>"""


def instagram_section(report):
    """Only a manual (browser-driven) run can collect Instagram.

    The automated run never has this data, so the section is omitted entirely
    rather than carrying a standing explanation of its own absence.
    """
    ig = report.get("instagram") or {}
    exact, fallback = ig.get("exact") or [], ig.get("fallback") or []
    if not exact and not fallback:
        return ""

    blocks = [f'<h2 class="section">📷 인스타그램 <span class="n">{len(exact) + len(fallback)}건</span></h2>']
    if exact:
        blocks.append(f'<h3 class="subsection">정확히 {esc(report["date"])} 게시 ({len(exact)}곳)</h3>')
        blocks.append(f'<div class="grid ig">{"".join(ig_card(i, False) for i in exact)}</div>')
    if fallback:
        blocks.append(
            f'<h3 class="subsection">최근 인기 게시물 (날짜 다름, {len(fallback)}곳)</h3>'
        )
        blocks.append(f'<div class="grid ig">{"".join(ig_card(i, True) for i in fallback)}</div>')
    return "\n".join(blocks)


def verify_panel(v):
    if not v:
        return ""
    soft = v.get("soft", [])
    tag = (
        '<span class="tag pass">검증 통과</span>'
        if not soft
        else '<span class="tag warn">검증 통과 · 참고사항 있음</span>'
    )
    notes = (
        f'<ul>{"".join(f"<li>{esc(s)}</li>" for s in soft)}</ul>' if soft else ""
    )
    return f"""<div class="verify">{tag}
    <span>발행 전 자동 검증 {esc(v.get('checkedAt', ''))} — 업로드일·조회수·중복·채널 편중·제외어 필터·수집 완결성 확인</span>
    {notes}</div>"""


def render(report, verify=None, archive_link="./archive/"):
    items = report["items"]
    grid = (
        f'<div class="grid">{"".join(card(it, i + 1) for i, it in enumerate(items))}</div>'
        if items
        else '<div class="empty">이 날짜에 조건을 충족하는 영상이 없습니다.</div>'
    )
    rej = report.get("rejected", {})
    launches = sum(1 for i in items if i.get("tier") == "신메뉴·신상")
    # Only explain the likes-vs-views distinction when Instagram data is
    # actually on the page; otherwise it explains something nobody can see.
    ig = report.get("instagram") or {}
    ig_note = (
        "<p><b>인스타그램 지표는 좋아요 수입니다.</b> 인스타그램은 로그인 없이 조회수를 "
        "공개하지 않으므로 좋아요 수를 쓰며, 유튜브 조회수와 한 순위로 섞지 않습니다. "
        "해당 날짜에 게시물이 없는 브랜드는 가장 최근 인기 게시물을 실제 날짜와 함께 "
        "보여줍니다.</p>"
        if (ig.get("exact") or ig.get("fallback"))
        else ""
    )
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(CONFIG['siteTitle'])} · {esc(report['date'])}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🍽️</text></svg>">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=Gothic+A1:wght@400;700;900&display=swap">
<style>{STYLE}</style></head><body><div class="wrap">
<header>
  <div>
    <p class="eyebrow">Trend Menu Clipping · YouTube · 매일 06:30 KST 자동 갱신</p>
    <h1>{esc(kst_label(report['date']))} 트렌드 메뉴 랭킹</h1>
  </div>
  <div class="head-meta">
    기준일 <b>{esc(report['date'])} (KST)</b><br>
    최소 조회수 <b>{fmt(report['viewThreshold'])}회</b><br>
    <a href="{archive_link}">지난 리포트 →</a>
  </div>
</header>
{verify_panel(verify)}
<div class="filter-bar">
  <span class="chip">업로드일 <b>{esc(report['date'])} 정확 일치</b></span>
  <span class="chip">조회수 <b>≥ {fmt(report['viewThreshold'])}회</b></span>
  <span class="chip">후보 <b>{fmt(report['candidateCount'])}건</b> → 게재 <b>{fmt(len(items))}건</b></span>
  <span class="chip">이 중 신메뉴·신상 <b>{launches}건</b></span>
</div>
<h2 class="section">▶ 유튜브 <span class="n">{len(items)}건</span></h2>
{grid}
{instagram_section(report)}
<details class="note">
  <summary>후보 {fmt(report['candidateCount'])}건 → 게재 {fmt(len(items))}건 · 집계 근거 보기</summary>
  <p><b>수집 방식:</b> 키워드 {len(report['keywords'])}개({esc(', '.join(report['keywords']))})로 후보 {fmt(report['candidateCount'])}건을 모은 뒤, 각 영상의 실제 업로드 시각과 조회수를 확인해 {esc(report['date'])}(KST)에 올라온 것만 남겼습니다. 화면에 적힌 숫자는 전부 해당 영상에서 직접 읽은 값입니다.</p>
  <p><b>탈락 내역:</b> 날짜 불일치 {rej.get('date', 0)}건 · 조회수 미달 {rej.get('views', 0)}건 · 주제 불일치 {rej.get('relevance', 0)}건 · 확인 불가 {rej.get('unverifiable', 0)}건. 조건을 통과한 {report.get('qualifiedCount', 0)}건 중 한 채널이 상위를 독식하지 않도록 채널당 최대 {CONFIG.get('perChannel', 2)}건으로 제한해 게재했습니다. 부족하면 빈자리를 채우지 않습니다.</p>
  {ig_note}
  <p>생성 {esc(report['generatedAt'])}</p>
</details>
</div></body></html>"""


def main():
    data_dir = ROOT / "data"
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        # Same date rule as build.py and verify.py — see verify.target_data_file
        # for why "the last file on disk" is the wrong default.
        override = os.environ.get("TARGET_DATE", "").strip()
        if override:
            try:
                day = dt.date.fromisoformat(override)
            except ValueError:
                sys.exit(f"TARGET_DATE={override!r} 형식이 잘못됐습니다 — YYYY-MM-DD 로 입력하세요")
        else:
            day = (dt.datetime.now(KST) - dt.timedelta(days=1)).date()
        path = data_dir / f"{day.isoformat()}.json"
        if not path.exists():
            sys.exit(f"{path.name} not found — run scripts/build.py first")

    report = json.loads(path.read_text(encoding="utf-8"))
    vpath = path.with_suffix(".verify.json")
    if not vpath.exists():
        sys.exit(f"{vpath.name} is missing — run scripts/verify.py before rendering")
    verify = json.loads(vpath.read_text(encoding="utf-8"))
    if not verify.get("passed"):
        sys.exit("verification did not pass — refusing to render")

    date = report["date"]
    docs, archive = ROOT / "docs", ROOT / "docs" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / f"{date}.html").write_text(render(report, verify, "./"), encoding="utf-8")

    dates = sorted(
        (p.stem for p in data_dir.glob("*.json") if len(p.stem) == 10), reverse=True
    )

    # The front page always shows the newest date on hand, not whichever date
    # this run happened to build. Backfilling an older day should add an archive
    # entry, not roll the front page backwards.
    newest = dates[0] if dates else date
    if newest == date:
        (docs / "index.html").write_text(render(report, verify), encoding="utf-8")
    else:
        newest_path = data_dir / f"{newest}.json"
        newest_verify = newest_path.with_suffix(".verify.json")
        if newest_verify.exists():
            (docs / "index.html").write_text(
                render(
                    json.loads(newest_path.read_text(encoding="utf-8")),
                    json.loads(newest_verify.read_text(encoding="utf-8")),
                ),
                encoding="utf-8",
            )
            print(f"front page left on {newest} (newer than the {date} build)")
    rows = "\n".join(f'<li><a href="./{d}.html">{d}</a></li>' for d in dates)
    (archive / "index.html").write_text(
        f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(CONFIG['siteTitle'])} · 지난 리포트</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px}}
a{{color:#e0451f;text-decoration:none;font-weight:700}} li{{margin:8px 0;font-size:15px}}</style>
</head><body><h1>지난 리포트</h1><ul>{rows or "<li>아직 기록이 없습니다.</li>"}</ul>
<p><a href="../">← 오늘 리포트</a></p></body></html>""",
        encoding="utf-8",
    )
    print(f"wrote docs/index.html, docs/archive/{date}.html, docs/archive/index.html")


if __name__ == "__main__":
    main()
