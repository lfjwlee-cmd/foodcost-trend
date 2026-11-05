#!/usr/bin/env python3
"""Weekly rollup — what repeated across the week, not what happened yesterday.

The daily page answers "what went up yesterday". It cannot answer the question
the daily page is actually read for: *is this a trend or a one-off?* Measured on
2026-09-16..22, 엽떡 '더 착한맛' drew 6 videos from 6 channels over 3 days while
the daily pages only ever showed 1-4 of them at a time. A week of ten-item
snapshots hides its own strongest signal.

So this page is about **events, not videos**. 70 videos collapse into the handful
of menus that more than one channel covered; everything else is a one-off and is
listed as such rather than padded out.

Reads only days whose quality gate passed (`<date>.verify.json`), so a bad
collection cannot quietly enter the weekly numbers.

Usage: python scripts/rollup.py            # the 7 days ending yesterday
       TARGET_DATE=2026-09-22 python scripts/rollup.py
       ROLLUP_DAYS=14 python scripts/rollup.py
"""

import datetime as dt
import html
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY = "월화수목금토일"
MIN_GRAM, MAX_GRAM = 3, 12


def _build():
    """build.py's brand rules, reused rather than reimplemented.

    Two copies of "what counts as a brand mention" would drift, and the weekly
    page would start disagreeing with the daily cards it links to.
    """
    spec = importlib.util.spec_from_file_location("build", ROOT / "scripts" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD = _build()


def _naver():
    """Loaded through the same path trick; returns None if the file is absent."""
    try:
        spec = importlib.util.spec_from_file_location("naver", ROOT / "scripts" / "naver.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def event_label(e):
    """The name shown on the page — and the exact string queried on Naver, so
    the two columns of one row are never about different things."""
    return (e["brand"] + " " if e["brand"] else "") + e["gram"]


_NV = _naver()


def esc(s):
    return html.escape(str(s), quote=True)


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def day_label(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def long_label(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.month}월 {d.day}일({WEEKDAY[d.weekday()]})"


def window():
    """The dates this rollup covers, oldest first.

    Ends on TARGET_DATE (or yesterday KST) to match build/verify/render, so a
    backfill of an old date rolls up that date's week rather than this one's.
    """
    override = os.environ.get("TARGET_DATE", "").strip()
    if override:
        try:
            end = dt.date.fromisoformat(override)
        except ValueError:
            sys.exit(f"TARGET_DATE={override!r} 형식이 잘못됐습니다 — YYYY-MM-DD 로 입력하세요")
    else:
        end = (dt.datetime.now(KST) - dt.timedelta(days=1)).date()
    n = int(os.environ.get("ROLLUP_DAYS") or CONFIG.get("rollupDays", 7))
    return [(end - dt.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def load_days(days):
    """(items, present_days, skipped) for the days that exist AND passed the gate."""
    items, present, skipped = [], [], []
    for d in days:
        path = ROOT / "data" / f"{d}.json"
        vpath = path.with_suffix(".verify.json")
        if not path.exists():
            continue
        if not vpath.exists() or not json.loads(vpath.read_text(encoding="utf-8")).get("passed"):
            skipped.append(d)
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for it in report.get("items", []):
            items.append(dict(it, day=report["date"]))
        present.append(d)
    return items, present, skipped


def segments(title, brand_forms, stops):
    """Title reduced to the chunks a menu name can come from.

    Spaces are joined, not split: the same product is written "더 착한 맛" and
    "더착한맛" on the same day, and splitting on spaces would file them apart.
    Punctuation, emoji and Latin text end a chunk. Brand names and stopwords are
    cut out — a brand belongs on its own axis, and a chunk containing "신메뉴"
    would otherwise make "신메뉴" the name of every event.
    """
    t = re.sub(r"\s+", "", title.lower())
    t = re.sub(r"[^가-힣]+", "|", t)
    for w in brand_forms + stops:
        t = t.replace(w.lower(), "|")
    return [s for s in t.split("|") if len(s) >= MIN_GRAM]


def group_events(items):
    """Videos grouped into the menu each is mainly about.

    Substring n-grams rather than a morphological analyser: Korean video titles
    are hashtag soup that a POS tagger mis-segments, while a repeated product
    name is by definition a repeated character run. No dictionary to maintain,
    and a menu nobody has heard of yet still groups.

    Each video joins exactly ONE event, strongest first. Without that, a single
    "9월 2주차 신상털이" roundup — one title naming six brands — lands in every
    group and drags its own headline brand into all of them. Verified on
    2026-09-20: that one video made 쇼콜라, 말차하임 and 트러플 all read as 엽떡.

    An event needs >= 2 videos from >= 2 channels. One channel posting twice is a
    sponsorship, not a trend, and that is exactly what the cut removes.
    """
    brand_forms = [f for f, _ in BUILD.brand_surface_forms() if not f.isascii()]
    stops = CONFIG.get("groupStopWords", [])
    grams = defaultdict(set)
    for idx, it in enumerate(items):
        for seg in segments(it.get("title") or "", brand_forms, stops):
            for size in range(MIN_GRAM, min(len(seg), MAX_GRAM) + 1):
                for k in range(len(seg) - size + 1):
                    grams[seg[k:k + size]].add(idx)

    order = sorted(
        (g for g, v in grams.items() if len(v) >= 2),
        key=lambda g: (-len(grams[g]), -len(g), g),
    )
    taken, events = set(), []
    for gram in order:
        mine = sorted(x for x in grams[gram] if x not in taken)
        if len(mine) < 2 or len({items[x]["channel"] for x in mine}) < 2:
            continue
        taken.update(mine)
        counts = Counter(b for x in mine for b in BUILD.brands_in(items[x].get("title") or ""))
        top = counts.most_common(1)
        # A brand names the event only if it is in MORE than half its videos.
        # ">= half" is too loose at the size most events are: one of two videos
        # mentioning 뚜레쥬르 labelled a 티라미수 group 뚜레쥬르 when the other
        # video was a different bakery's. A tie means the event has no one brand.
        brand = top[0][0] if top and top[0][1] * 2 > len(mine) else None
        events.append({
            "gram": gram,
            "brand": brand,
            "idx": mine,
            "count": len(mine),
            "channels": len({items[x]["channel"] for x in mine}),
            "days": sorted({items[x]["day"] for x in mine}),
            "views": sum(items[x].get("views") or 0 for x in mine),
            "likes": sum(
                items[x]["likes"] for x in mine if isinstance(items[x].get("likes"), int)
            ),
        })
    events.sort(key=lambda e: (-e["count"], -len(e["days"]), -e["views"]))
    return events, sorted(set(range(len(items))) - taken)


def prior_grams(days):
    """Event names seen in the window immediately before this one.

    Used only to mark "new this week". With fewer than 3 prior days on disk the
    comparison would call everything new, so the caller drops the badge instead.
    """
    if not days:
        return set(), 0
    first = dt.date.fromisoformat(days[0])
    prev = [(first - dt.timedelta(days=i)).isoformat() for i in range(len(days), 0, -1)]
    items, present, _ = load_days(prev)
    if len(present) < 3:
        return set(), len(present)
    events, _ = group_events(items)
    return {e["gram"] for e in events}, len(present)


# One hue, light -> dark, for magnitude. Categories get one colour each, never a
# ramp; a ramp here is legitimate because every cell encodes the same measure
# (videos that day). Dark mode is stepped against the dark surface rather than
# flipped, or the low steps disappear into the background.
STYLE = """
:root{--bg:#faf5ee;--surface:#fff;--surface-2:#f2e9dc;--line:#e6dac8;--ink:#241b12;
--ink-dim:#7a6c58;--accent:#e0451f;--accent-ink:#fff7f0;--gold:#c8860a;--ok:#2f7d55;
--s0:#f0e6d8;--s1:#fbdcc8;--s2:#f5b591;--s3:#ec8152;--s4:#e0451f;
--s-ink-lo:#3a2a1c;--s-ink-hi:#fff7f0}
@media (prefers-color-scheme:dark){:root{--bg:#171210;--surface:#211a15;--surface-2:#2a2119;
--line:#3a2d22;--ink:#f4ebdd;--ink-dim:#a99884;--accent:#ff6a3d;--accent-ink:#1a0f08;
--gold:#f3b632;--ok:#63c294;
--s0:#2a2119;--s1:#46281c;--s2:#6d3921;--s3:#b04f28;--s4:#ff6a3d;
--s-ink-lo:#f4ebdd;--s-ink-hi:#1a0f08}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Gothic A1',system-ui,sans-serif;
padding:32px clamp(16px,4vw,48px) 56px}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:20px;
padding-bottom:22px;margin-bottom:22px;border-bottom:3px solid var(--ink)}
.eyebrow{font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--accent);
text-transform:uppercase;margin:0 0 6px}
h1{font-family:'Black Han Sans',sans-serif;font-weight:400;font-size:clamp(28px,4.4vw,44px);
line-height:1.1;margin:0}
.head-meta{text-align:right;font-size:13px;color:var(--ink-dim);line-height:1.7}
.head-meta b{color:var(--ink)}
.head-meta a{color:var(--accent);text-decoration:none;font-weight:700}
.lede{font-size:clamp(17px,2.4vw,22px);line-height:1.5;font-weight:700;margin:0 0 18px}
.lede b{color:var(--accent)}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:30px}
@media (max-width:980px){.tiles{grid-template-columns:repeat(2,1fr)}}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
min-width:0}
.tile .k{font-size:12px;font-weight:700;color:var(--ink-dim);margin-bottom:5px}
.tile .v{font-size:clamp(22px,3.2vw,30px);font-weight:900;line-height:1.1}
.tile .s{font-size:12px;color:var(--ink-dim);margin-top:4px;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
h2.section{font-family:'Black Han Sans',sans-serif;font-weight:400;font-size:19px;
margin:34px 0 4px;display:flex;align-items:center;gap:9px}
h2.section:first-of-type{margin-top:0}
p.hint{font-size:12.5px;color:var(--ink-dim);margin:0 0 14px;line-height:1.6}
.ev{border:1px solid var(--line);border-radius:12px;background:var(--surface);margin-bottom:8px}
.ev>summary{list-style:none;cursor:pointer;display:grid;align-items:center;gap:12px;padding:12px 14px;
grid-template-columns:26px minmax(0,1.3fr) minmax(70px,1fr) 52px auto auto}
.ev>summary::-webkit-details-marker{display:none}
.ev>summary:hover{background:var(--surface-2)}
.ev .rk{font-family:'Black Han Sans',sans-serif;font-size:17px;color:var(--ink-dim);text-align:center}
.ev:first-of-type .rk{color:var(--accent)}
.ev .nm{font-size:15px;font-weight:700;line-height:1.3;min-width:0;overflow-wrap:anywhere}
.ev .nm .br{color:var(--accent)}
.ev .nm .new{font-size:10px;font-weight:900;background:var(--gold);color:#1a0f08;
border-radius:999px;padding:1px 7px;margin-left:6px;vertical-align:2px}
.ev .bar{height:9px;background:var(--surface-2);border-radius:999px;overflow:hidden}
.ev .bar i{display:block;height:100%;background:var(--accent);border-radius:999px}
.ev .n{font-size:13px;font-weight:900;font-variant-numeric:tabular-nums}
.ev .mx{display:flex;gap:14px;justify-content:flex-end}
.ev .mt{text-align:right;min-width:52px}
.ev .mt b{display:block;font-size:13px;font-weight:900;font-variant-numeric:tabular-nums}
.ev .mt i{display:block;font-style:normal;font-size:10px;color:var(--ink-dim);font-weight:700}
.ev .mt.vw b{color:var(--gold)}
.ev .mt.nv b{color:var(--ink)}
.ev .mt.rt b{color:var(--ok)}
.ev .mt.nv b.cap::after{content:"+";font-size:11px}
.strip{display:flex;gap:2px}
.strip i{width:15px;height:20px;border-radius:3px;background:var(--s0);display:block}
.s1{background:var(--s1)!important}.s2{background:var(--s2)!important}
.s3{background:var(--s3)!important}.s4{background:var(--s4)!important}
.ev ul{margin:0;padding:2px 14px 14px 52px;border-top:1px solid var(--line);list-style:none}
.ev li{font-size:13px;line-height:1.5;padding:7px 0;border-bottom:1px solid var(--line)}
.ev li:last-child{border-bottom:none}
.ev li a{color:var(--ink);text-decoration:none;font-weight:700}
.ev li a:hover{color:var(--accent)}
.ev li .m{color:var(--ink-dim);font-weight:400;font-size:12px}
.legend{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--ink-dim);margin:10px 0 0}
.legend i{width:15px;height:13px;border-radius:3px;display:block;background:var(--s0)}
table.heat{border-collapse:separate;border-spacing:2px;font-size:12.5px;width:100%}
table.heat th{font-weight:700;color:var(--ink-dim);font-size:11.5px;padding:3px 5px;text-align:center}
table.heat th.b{text-align:left;white-space:nowrap;color:var(--ink);font-size:12.5px}
table.heat td{text-align:center;border-radius:4px;background:var(--s0);color:var(--s-ink-lo);
padding:6px 0;font-variant-numeric:tabular-nums;min-width:30px}
table.heat td.s3,table.heat td.s4{color:var(--s-ink-hi);font-weight:900}
table.heat td.z{color:transparent}
table.heat tr th.tot,table.heat td.tot{background:transparent;color:var(--ink);font-weight:900}
.scroll{overflow-x:auto}
ol.solo{margin:0;padding-left:20px}
ol.solo li{font-size:13.5px;line-height:1.5;margin-bottom:9px}
ol.solo a{color:var(--ink);font-weight:700;text-decoration:none}
ol.solo a:hover{color:var(--accent)}
ol.solo .m{display:block;color:var(--ink-dim);font-weight:400;font-size:12px;margin-top:2px}
.note{border-top:1px solid var(--line);margin-top:34px;padding-top:16px;font-size:12.5px;
color:var(--ink-dim);line-height:1.75}
.note b{color:var(--ink)}
.note p{margin:10px 0 0}
.note summary{cursor:pointer;font-weight:700;list-style:none}
.note summary::-webkit-details-marker{display:none}
.note summary::before{content:"\25B8 ";color:var(--accent)}
.note[open] summary::before{content:"\25BE "}
/* Narrow: the six-column grid cannot hold, and juggling grid-column on each
   child put the weekday strip outside its own card. Flex with an explicit order
   wraps into three honest lines instead: name, bar, then count + strip. */
@media (max-width:720px){
  .tiles{grid-template-columns:1fr}
  .ev>summary{display:flex;flex-wrap:wrap;align-items:center;gap:9px}
  .ev .rk{flex:0 0 18px;text-align:left}
  .ev .nm{flex:1 1 0;min-width:0}
  .ev .mx{flex:0 0 auto;order:3;gap:12px}
  .ev .bar{flex:1 1 100%;order:4}
  .ev .n{order:5}
  .strip{order:6;margin-left:auto}
  .ev ul{padding-left:16px}
}
"""


def step(n):
    """Ramp step for a day cell. 0 is absence and gets no colour.

    A count normalised against the week's maximum looked right on paper and was
    unreadable in practice: a day holds 1-4 videos, so nearly every cell landed
    on the palest step and "appeared that day" was indistinguishable from "did
    not". The counts are small integers, so the ladder is the count itself —
    and the legend can then name each step instead of pointing at a gradient.
    """
    return (0, 2, 3)[n] if n < 3 else 4


def event_rows(events, items, days, new_grams, naver):
    top_n = max(e["count"] for e in events)
    out = []
    for rank, e in enumerate(events, 1):
        per_day = [sum(1 for x in e["idx"] if items[x]["day"] == d) for d in days]
        strip = "".join(
            f'<i class="s{step(n)}" title="{esc(long_label(d))} · {n}건"></i>'
            for d, n in zip(days, per_day)
        )
        brand = f'<span class="br">{esc(e["brand"])}</span> ' if e["brand"] else ""
        new = '<span class="new">NEW</span>' if e["gram"] in new_grams else ""
        vids = "".join(
            f'<li><a href="{esc(items[x]["url"])}" target="_blank" rel="noopener">'
            f'{esc(items[x]["title"])}</a>'
            f'<span class="m"> — {esc(items[x]["channel"])} · 조회수 {fmt(items[x]["views"])}회 · '
            f'{esc(long_label(items[x]["day"]))}</span></li>'
            for x in sorted(e["idx"], key=lambda x: -(items[x].get("views") or 0))
        )
        # 조회수는 "얼마나 노출됐나"이고 알고리즘과 채널 규모가 대부분을 정한다.
        # 반응률은 "본 사람 중 몇 %가 반응했나"라서 콘텐츠 자체의 힘에 가깝다.
        # 실측(최근 14일 140건): 중앙값 0.93%, 하위 10% 0.27%, 상위 10% 2.30% —
        # 8배가 벌어지므로 줄을 가르는 눈금으로 쓸 만하다.
        rate = e["likes"] / e["views"] if e["views"] and e["likes"] else None
        rate_cell = (
            f'<span class="mt rt"><b>{rate * 100:.1f}%</b><i>반응률</i></span>'
            if rate
            else ""
        )
        nv = (naver or {}).get(event_label(e))
        nv_cell = (
            f'<span class="mt nv"><b class="{"cap" if nv["capped"] else ""}">'
            f'{fmt(nv["count"])}</b><i>블로그</i></span>'
            if nv
            else ""
        )
        width = e["count"] / top_n * 100
        out.append(f"""
    <details class="ev">
      <summary>
        <span class="rk">{rank}</span>
        <span class="nm">{brand}{esc(e['gram'])}{new}</span>
        <span class="bar" title="{e['count']}건"><i style="width:{width:.0f}%"></i></span>
        <span class="n">{e['count']}건</span>
        <span class="strip">{strip}</span>
        <span class="mx"><span class="mt vw"><b>{fmt(e['views'])}</b><i>조회수</i></span>{rate_cell}{nv_cell}</span>
      </summary>
      <ul>{vids}</ul>
    </details>""")
    return "\n".join(out)


def heatmap(items, days):
    """브랜드 × 날짜.

    셀마다 숫자를 그대로 적는다. 색은 이미 적혀 있는 값을 한 번 더 읽는 수단이지,
    값에 닿는 유일한 경로가 아니다 — 색만으로 읽히는 표는 접근성에서 실패한다.
    """
    rows = defaultdict(lambda: defaultdict(int))
    for it in items:
        for b in BUILD.brands_in(it.get("title") or ""):
            rows[b][it["day"]] += 1
    if not rows:
        return '<p class="hint">등록된 브랜드가 언급된 영상이 없습니다.</p>'
    ranked = sorted(rows.items(), key=lambda kv: -sum(kv[1].values()))[:12]
    head = "".join(
        f'<th>{esc(day_label(d))}<br>{WEEKDAY[dt.date.fromisoformat(d).weekday()]}</th>'
        for d in days
    )
    body = []
    for brand, per in ranked:
        cells = "".join(
            f'<td class="s{step(per.get(d, 0))}{"" if per.get(d) else " z"}" '
            f'title="{esc(brand)} · {esc(long_label(d))} · {per.get(d, 0)}건">{per.get(d, 0)}</td>'
            for d in days
        )
        body.append(
            f'<tr><th class="b">{esc(brand)}</th>{cells}'
            f'<td class="tot">{sum(per.values())}</td></tr>'
        )
    return f"""
<div class="scroll"><table class="heat">
  <thead><tr><th class="b">브랜드</th>{head}<th class="tot">합계</th></tr></thead>
  <tbody>{"".join(body)}</tbody>
</table></div>"""


def render(items, days, events, solo, skipped, new_grams, prior_days, naver):
    total_views = sum(i.get("views") or 0 for i in items)
    best = max(items, key=lambda i: i.get("views") or 0) if items else None
    if events:
        top = events[0]
        name = (top["brand"] + " " if top["brand"] else "") + top["gram"]
        lede = (
            f'이번 주 1위는 <b>{esc(name)}</b> — '
            f'{len(top["days"])}일에 걸쳐 {top["channels"]}개 채널이 {top["count"]}건을 올렸습니다.'
        )
    else:
        lede = "이번 주에는 두 채널 이상이 함께 다룬 메뉴가 없었습니다 — 전부 단발이었습니다."

    grouped = sum(e["count"] for e in events)
    # isShort only exists on data collected after this field was added, so a
    # window that reaches back before then would silently read as 0% short.
    # Count the measurable subset and say how big it is.
    known = [i for i in items if i.get("isShort") is not None]
    shorts = sum(1 for i in known if i["isShort"])
    short_pct = f"{shorts / len(known):.0%}" if known else "—"
    short_note = (
        f"{len(known)}건 중 {shorts}건"
        + ("" if len(known) == len(items) else f" · 길이 미기록 {len(items) - len(known)}건 제외")
        if known
        else "이 기간 데이터에는 영상 길이가 없습니다"
    )
    tiles = f"""
<div class="tiles">
  <div class="tile"><div class="k">수집</div><div class="v">{len(items)}건</div>
    <div class="s">{len(days)}일 · 누적 조회수 {fmt(total_views)}회</div></div>
  <div class="tile"><div class="k">반복 등장한 메뉴</div><div class="v">{len(events)}건</div>
    <div class="s">영상 {grouped}건이 여기 묶임 · 나머지 {len(solo)}건은 단발</div></div>
  <div class="tile"><div class="k">60초 이하 짧은 영상</div>
    <div class="v">{short_pct}</div>
    <div class="s">{short_note}</div></div>
  <div class="tile"><div class="k">최고 조회</div>
    <div class="v">{fmt(best['views']) if best else 0}회</div>
    <div class="s">{esc(best['title']) if best else '—'}</div></div>
</div>"""

    legend = (
        '<p class="legend">하루 게재량 <i></i>없음 <i class="s2"></i>1건 '
        '<i class="s3"></i>2건 <i class="s4"></i>3건 이상</p>'
    )
    events_html = (
        event_rows(events, items, days, new_grams, naver) + legend
        if events
        else '<p class="hint">두 채널 이상이 함께 다룬 메뉴가 없습니다.</p>'
    )
    solo_html = "".join(
        f'<li><a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["title"])}</a>'
        f'<span class="m">{esc(i["channel"])} · 조회수 {fmt(i["views"])}회 · '
        f'{esc(long_label(i["day"]))}</span></li>'
        for i in sorted(solo, key=lambda i: -(i.get("views") or 0))[:5]
    )
    skip_note = (
        f'<p><b>제외된 날:</b> {esc(", ".join(skipped))} — 검증을 통과하지 못했거나 '
        f'검증 기록이 없어 집계에서 뺐습니다.</p>'
        if skipped
        else ""
    )
    new_note = (
        f"직전 {prior_days}일과 대조해 그때 없던 메뉴에 NEW를 붙였습니다."
        if prior_days >= 3
        else f"직전 기간 데이터가 {prior_days}일치뿐이라 NEW 표시는 생략했습니다."
    )
    if naver is None:
        naver_note = (
            "쓰지 않았습니다. 네이버 검색 API는 요금이 붙을 수 있어 기본값은 꺼짐이고, "
            "이 페이지의 '확산' 축은 키가 필요 없는 반응률이 대신합니다. "
            "자격증명을 넣으면 열이 추가되지만, 요금 정책은 직접 확인하세요."
        )
    else:
        naver_note = (
            "같은 기간 네이버 블로그에 올라온 글 수입니다. 검색 API의 total은 역대 "
            f"전체 건수라 기간을 못 가르므로, 날짜순으로 최대 {_NV.MAX_PAGES * _NV.PER_PAGE}건까지 "
            "훑어 기간 안에 든 것만 셉니다. 숫자 뒤의 +는 거기서 잘렸다는 뜻으로, 실제는 "
            "더 많습니다. 카페 검색에는 날짜 필드가 없어 블로그만 집계합니다."
        )
    title = f"{CONFIG['siteTitle']} · 주간 롤업 {days[0]}~{days[-1]}"
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>&#128202;</text></svg>">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=Gothic+A1:wght@400;700;900&display=swap">
<style>{STYLE}</style></head><body><div class="wrap">
<header>
  <div>
    <p class="eyebrow">Weekly Rollup · {esc(days[0])} ~ {esc(days[-1])} (KST)</p>
    <h1>이번 주 반복된 메뉴</h1>
  </div>
  <div class="head-meta">
    집계 <b>{len(days)}일 · {len(items)}건</b><br>
    <a href="./index.html">오늘 리포트 →</a><br>
    <a href="./archive/">지난 리포트 →</a>
  </div>
</header>
<p class="lede">{lede}</p>
{tiles}
<h2 class="section">반복 등장한 메뉴</h2>
<p class="hint">서로 다른 채널 2곳 이상이 같은 메뉴를 다룬 것만 셉니다. 한 채널이 두 번 올린 것은
협찬이지 트렌드가 아니므로 제외합니다. 줄을 누르면 실제 영상이 펼쳐집니다.</p>
{events_html}
<h2 class="section">브랜드 언급</h2>
<p class="hint">제목에 등록 브랜드가 나온 횟수입니다. 한 제목이 두 브랜드를 말하면 양쪽에 셉니다.</p>
{heatmap(items, days)}
<h2 class="section">단발 하이라이트</h2>
<p class="hint">다른 채널이 따라가지 않은 단독 영상 {len(solo)}건 중 조회수 상위 5건입니다.</p>
<ol class="solo">{solo_html or "<li>없습니다.</li>"}</ol>
<details class="note">
  <summary>집계 방법 보기</summary>
  <p><b>대상:</b> {esc(days[0])}~{esc(days[-1])} 중 검증을 통과한 {len(days)}일의 일간 리포트
  {len(items)}건입니다. 숫자는 전부 일간 리포트에 이미 실린 값이고, 여기서 다시 세기만 합니다.</p>
  <p><b>묶는 방법:</b> 제목에서 브랜드명과 상투어(신메뉴·먹방·리뷰 등)를 걷어낸 뒤, 2건 이상에
  공통으로 나타나는 3~12글자 덩어리를 메뉴 이름으로 봅니다. 사전을 쓰지 않으므로 처음 나온
  메뉴도 묶입니다. 한 영상은 가장 강한 사건 하나에만 들어갑니다 — 여러 브랜드를 한꺼번에
  나열하는 '이번 주 신상털이' 류 영상이 모든 그룹에 끼어들어 브랜드를 잘못 붙이기 때문입니다.</p>
  <p><b>NEW 표시:</b> {esc(new_note)}</p>
  <p><b>반응률:</b> 그 사건에 묶인 영상의 좋아요 합을 조회수 합으로 나눈 값입니다.
  조회수는 얼마나 노출됐는지를 말하고 알고리즘과 채널 규모가 대부분을 정하는 반면,
  반응률은 본 사람 중 몇 %가 반응했는지라 콘텐츠 자체에 더 가깝습니다. 최근 14일
  140건 기준 중앙값 0.93%, 하위 10% 0.27%, 상위 10% 2.30%입니다. 좋아요를 끈
  영상은 분자에서 빠집니다.</p>
  <p><b>블로그 열:</b> {esc(naver_note)}</p>
  <p><b>짧은 영상:</b> 길이 {CONFIG.get('shortMaxSeconds', 60)}초 이하이거나 제목·설명에
  #shorts 가 붙은 것을 셉니다. 유튜브가 쇼츠 상한을 3분으로 올린 뒤로 길이만으로는
  쇼츠인지 증명할 수 없고 API도 /shorts/ 주소를 주지 않아, '쇼츠'라고 단정하지 않고
  짧은 영상이라고만 적습니다.</p>
  {skip_note}
  <p>생성 {esc(dt.datetime.now(KST).isoformat(timespec='seconds'))}</p>
</details>
</div></body></html>"""


def main():
    days = window()
    items, present, skipped = load_days(days)
    if not present:
        sys.exit(f"{days[0]}~{days[-1]} 구간에 검증을 통과한 일간 리포트가 없습니다")
    events, solo_idx = group_events(items)
    new_grams, prior_days = prior_grams(present)
    solo = [items[x] for x in solo_idx]
    naver = None
    if _NV and events:
        naver = _NV.mentions([event_label(e) for e in events], present[0], present[-1])
        if naver is None:
            print("  네이버 열 생략 — 자격증명이 없거나 호출이 실패했습니다")
    out = ROOT / "docs" / "weekly.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render(items, present, events, solo, skipped, new_grams, prior_days, naver),
        encoding="utf-8",
    )
    print(f"주간 롤업 {present[0]}~{present[-1]} · {len(items)}건 "
          f"→ 사건 {len(events)}개, 단발 {len(solo)}건")
    for e in events:
        name = (e["brand"] + " " if e["brand"] else "") + e["gram"]
        print(f"  {e['count']}건 {e['channels']}채널 {len(e['days'])}일  {name}")
    if skipped:
        print(f"  (검증 미통과로 제외: {', '.join(skipped)})")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
