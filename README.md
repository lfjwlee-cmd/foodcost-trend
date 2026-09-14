# 트렌드 메뉴 클리핑 (foodcost-trend)

매일 오전 6시 30분(KST)에 자동으로 전날 올라온 한국 음식·신메뉴 유튜브 콘텐츠를 모아
벤토그리드 HTML 리포트로 발행합니다.

## 시작하기 전에: 유튜브 API 키 (무료, 5분)

GitHub Actions에서 돌리려면 키가 필요합니다. 실측 결과 GitHub 서버 IP에서는 유튜브가
개별 영상 조회를 전부 차단합니다(40건 중 40건 `Sign in to confirm you're not a bot`).
집 네트워크에서 직접 돌릴 때는 키 없이도 동작합니다.

1. https://console.cloud.google.com → 새 프로젝트 생성
2. API 및 서비스 → 라이브러리 → **YouTube Data API v3** → 사용 설정
3. 사용자 인증정보 → 사용자 인증정보 만들기 → **API 키** → 복사
4. 이 저장소 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `YOUTUBE_API_KEY`, Value: 복사한 키

비용은 들지 않습니다. 하루 무료 할당량 10,000 유닛 중 약 610 유닛만 씁니다.

- 오늘 리포트: `docs/index.html`
- 지난 리포트: `docs/archive/`
- 원본 데이터: `data/<날짜>.json` (매 실행마다 하루치가 쌓입니다)

## 동작 방식

수집 → **검증** → 발행 3단계이고, 검증을 통과하지 못하면 발행하지 않습니다.

1. **수집** (`scripts/build.py`) — `config.json`의 키워드로 검색해 후보를 모으고,
   각 영상의 실제 업로드 시각과 조회수를 확인합니다. **KST 기준 어제 하루에 정확히
   올라온 것**만 남기고 조회수 하한(기본 1,000회)과 주제 관련성을 적용한 뒤,
   채널당 최대 2건으로 제한해 상위 10건을 추립니다.
2. **검증** (`scripts/verify.py`) — 발행 전 자동 점검. 네 가지 관점을 코드로 옮긴 것입니다.
   - 감사역: 업로드일·조회수가 리포트가 주장하는 조건과 실제로 맞는지, 중복은 없는지
   - 엔지니어: 수집이 완결됐는지(확인 불가 비율 20% 초과면 실패)
   - 마케팅: 한 채널이 상한을 넘지 않았는지, 게재 건수가 너무 적지는 않은지
   - 경영진: 실제 신메뉴·신상이 몇 건인지, 등록 브랜드 언급이 있는지
3. **발행** (`scripts/render.py`) — 검증을 통과한 경우에만 `docs/`를 갱신합니다.

검증 실패(하드)는 발행을 막고 **전날 페이지를 그대로 둡니다.** 잘못된 리포트로 덮어쓰는
것보다 낫기 때문입니다. 경고(소프트)는 발행하되 페이지 상단에 그대로 표시합니다.

숫자는 전부 해당 영상에서 직접 읽은 값입니다. 조건을 통과한 영상이 10건이 안 되면
빈자리를 채우지 않고 그만큼만 싣고, 탈락 사유별 건수를 리포트 하단에 남깁니다.

## 설정 바꾸기

`config.json`만 고치면 됩니다. 코드는 건드릴 필요가 없습니다.

| 항목 | 뜻 |
|---|---|
| `keywords` | 검색할 키워드. 업종·브랜드에 맞게 바꾸면 결과 성격이 바뀝니다 |
| `viewThreshold` | 조회수 하한 (기본 1,000) |
| `topN` | 최종 게재 건수 (기본 10) |
| `perChannel` | 한 채널에서 최대 몇 건까지 실을지 (기본 2) |
| `includeWords` / `excludeWords` | 주제 관련성 판정에 쓰는 단어들 |
| `brandTags` | 제목에 있으면 카드에 브랜드 칩으로 표시할 이름들 |

## 직접 돌려보기

```bash
pip install yt-dlp                      # 키 없이 로컬 실행할 때만 필요
python scripts/build.py                 # 수집 (어제 기준)
python scripts/verify.py                # 검증 — 실패하면 여기서 멈춤
python scripts/render.py                # 발행

TARGET_DATE=2026-09-09 python scripts/build.py   # 특정 날짜
YOUTUBE_API_KEY=xxx python scripts/build.py      # 공식 API로 수집
```

GitHub에서는 Actions 탭 → "Daily Trend Menu Report" → Run workflow로 수동 실행할 수 있습니다.

## 네이버 언급 집계 (선택)

`NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` 시크릿을 등록하면 켜집니다. 없으면 그 섹션만
비활성으로 표시되고 나머지는 그대로 돕니다.

1. https://developers.naver.com → 애플리케이션 등록 → **검색** API 선택
2. 발급된 Client ID / Client Secret을 저장소 Secrets에 등록
3. `config.json`의 `naverWatchTerms`에 추적할 브랜드·메뉴 키워드를 넣습니다

**이 수치는 순위가 아니라 언급 건수입니다.** 네이버 검색 API가 돌려주는 필드는
`title` · `link` · `description` · `bloggername` · `postdate`(카페는 `cafename`·`cafeurl` 추가)뿐이고,
**조회수·좋아요·댓글 수는 제공하지 않습니다.** 그래서 유튜브처럼 정렬·하한을 걸 수 없고,
"어제 이 브랜드가 블로그·카페에서 몇 번 언급됐나"만 셉니다. 유튜브가 "뭘 봤나"라면 이건
"뭘 썼나"에 해당하는 다른 신호이므로, 리포트에서도 두 숫자를 섞지 않고 따로 보여줍니다.

집계가 `100건+`로 표시되면 API 한 페이지(100건)를 채웠다는 뜻이며 실제로는 더 많습니다.

> ⚠️ 네이버가 검색 API를 **NAVER API HUB**로 이전 중이며, 기존 Developers Center 키는
> **2027-06-30**에 중지될 예정입니다. 그 전에 한 번 갈아타야 합니다.

## 인스타그램이 없는 이유

인스타그램은 해시태그·키워드 검색이 로그인 없이 막혀 있고, 조회수도 비로그인 상태에서는
공개되지 않습니다. 무인 자동화로 신뢰할 수 있는 수치를 얻을 방법이 없어서, 숫자를 지어내는
대신 아예 제외했습니다. 브랜드 계정을 직접 지정해 확인하는 방식은 사람이 실행하는
`trend-menu-clipper` 스킬 쪽에 따로 들어 있습니다.
