# 대시보드 데이터 스키마 & 연결 구조

> 생성 스크립트: `src/build_actor_dashboard.py`  
> 소스: `data/manual/seo_kyungsu_manual.csv` + KOPIS cast CSV

---

## 테이블 관계

```
01_career_timeline          03_characters
  seq (PK) ─────────────── seq (FK)   ← 주·조연 역할만 필터된 뷰
      │
      └──────────────────── seq (FK)   ← 04_companies (제작사별 행 분리)
                            04_companies

02_costar_network                      ← 독립 테이블 (Tableau에서 별도 연결)
```

`seq`가 유일 PK. 같은 공연명이 여러 번 등장하기 때문에  
`공연명` 단독으로는 조인 키로 쓸 수 없음.

---

## 01_career_timeline.csv — 메인 테이블 (50행)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `seq` | INT | **PK** — 공연 순번 1~50 (시간순) |
| `공연명` | STRING | 작품 제목 (중복 있음) |
| `역할명` | STRING | 서경수의 캐릭터명 (e.g. 잭 켈리, 앙상블) |
| `역할구분` | STRING | **앙상블 / 스윙 / 조연 / 주연** |
| `공연유형` | STRING | **정규 / 국내 초연 / 앙콜 / 연장 / 특별공연** |
| `시작일` | DATE | YYYY-MM-DD |
| `종료일` | DATE | YYYY-MM-DD |
| `연도` | INT | 시작 연도 |
| `기간_일수` | INT | (종료일 - 시작일) + 1 |
| `장르` | STRING | 뮤지컬 / 연극 |
| `공연장` | STRING | 극장명 |
| `지역` | STRING | 서울특별시 등 |
| `제작사` | STRING | 쉼표 구분 (복수 가능) |
| `비고` | STRING | 원본 메모 (초연, 앙콜 등) |

**주요 사용처**
- Sheet 1 Hero: COUNTD, SUM 집계
- Sheet 2 Timeline Gantt: `시작일` + `기간_일수` (크기), `역할구분` (색상)

---

## 02_costar_network.csv — 공동출연 네트워크 (151명)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `공동출연_배우` | STRING | **PK** — 공동출연 배우 이름 |
| `공동출연_횟수` | INT | 서경수와 함께한 공연 수 |
| `공동출연_작품` | STRING | 작품명 목록 (쉼표 구분, 참고용) |

> Tableau 조인 없이 **독립 시트**로 사용.  
> `공동출연_횟수`를 원 크기 / 바 길이로 인코딩.

**주요 사용처**
- Sheet 3 Network: 버블차트 or 바차트, 상위 N명 필터

---

## 03_characters.csv — 캐릭터 그리드 (44개)

앙상블·스윙을 제외한 주·조연 역할만 추출한 뷰.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `seq` | INT | **FK → 01_career_timeline.seq** |
| `공연명` | STRING | |
| `역할명` | STRING | 캐릭터명 |
| `역할구분` | STRING | 조연 / 주연 |
| `공연유형` | STRING | 정규 / 국내 초연 등 |
| `연도` | INT | |
| `시작일` | DATE | |
| `장르` | STRING | |

**주요 사용처**
- Sheet 4 Characters: 텍스트 테이블 or 도형 그리드  
  (`역할명` 텍스트 + `역할구분` 색상 + `연도` 정렬)

---

## 04_companies.csv — 제작사 동선 (12건)

제작사가 복수인 공연은 행 분리됨 (e.g. "A, B" → 2행).

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `seq` | INT | **FK → 01_career_timeline.seq** |
| `제작사` | STRING | 개별 제작사명 |
| `공연명` | STRING | |
| `연도` | INT | |
| `시작일` | DATE | |
| `역할구분` | STRING | |
| `장르` | STRING | |

**주요 사용처**
- Sheet 5 Companies: 타임라인 or 산점도  
  (X축 `연도`, Y축 or 색상 `제작사`, 크기 `공연_수`)

---

## Tableau 데이터 소스 구성

```
[메인 데이터 소스]
01_career_timeline
  ├── LEFT JOIN 03_characters  ON seq = seq
  └── LEFT JOIN 04_companies   ON seq = seq

[별도 데이터 소스]
02_costar_network  (단독 연결, 조인 없음)
```

> 03, 04는 01의 필터링·분해 뷰이므로 조인해도 행 수가 늘어나지 않음.  
> (03은 동일 seq당 1행, 04는 제작사 복수일 때 n행으로 늘어날 수 있음)

---

## Hero 카드 계산식 (Sheet 1)

| 카드 | Tableau 계산식 |
|------|---------------|
| 총 공연 수 | `COUNTD([seq])` |
| 주연 비율 | `SUM(IF [역할구분]="주연" THEN 1 ELSE 0 END) / COUNTD([seq])` |
| 국내 초연 수 | `SUM(IF [공연유형]="국내 초연" THEN 1 ELSE 0 END)` |
| 활동 연수 | `MAX([연도]) - MIN([연도]) + 1` |
