"""
서경수 배우 중심 Tableau 대시보드 데이터 빌드

입력:
  data/manual/seo_kyungsu_manual.csv  — 50편 경력 + 배역·비고 (정의 소스)
  data/legacy/cast.csv                — 2009-2020 공동출연 (KOPIS + MANUAL)
  data/cast.csv                       — 2021-2026 공동출연 (KOPIS)
  data/legacy/performances.csv        — 레거시 공연 마스터
  data/performances.csv               — 메인 공연 마스터

출력 (data/dashboard/):
  01_career_timeline.csv  — Gantt + Hero 카드용 (50행)
  02_costar_network.csv   — 공동출연 네트워크 에지
  03_characters.csv       — 캐릭터 그리드용 (주·조연만)
  04_companies.csv        — 제작사 동선용

사용법:
  python3 src/build_actor_dashboard.py
"""

import csv
from datetime import date
from pathlib import Path
from collections import defaultdict

MANUAL_CSV  = Path("data/manual/seo_kyungsu_manual.csv")
LEGACY_CAST = Path("data/legacy/cast.csv")
MAIN_CAST   = Path("data/cast.csv")
LEGACY_PERF = Path("data/legacy/performances.csv")
MAIN_PERF   = Path("data/performances.csv")
OUT_DIR     = Path("data/dashboard")
TARGET      = "서경수"

# ── 역할 구분 분류 ────────────────────────────────────────────────────────────
LEAD_SHOWS = {
    "런투유", "넥스트 투 노멀", "마마 돈 크라이", "베어 더 뮤지컬",
    "뉴시즈", "오! 캐롤", "시라노", "신과 함께 저승편", "이블데드",
    "젠틀맨스 가이드: 사랑과 살인편", "그리스", "여신님이 보고 계셔",
    "차미", "브로드웨이 42번가", "썸씽 로튼", "위키드", "레드북",
    "데스노트", "킹키부츠", "벤허", "일 테노레", "알라딘",
}
SUPPORT_SHOWS = {
    "한 여름밤의 꿈", "금발이 너무해", "헤이 자나!", "카르멘",
    "정글라이프", "트레이스 유", "블랙메리포핀스", "라카지",
    "인 더 하이츠", "타이타닉",
}


def classify_role(prfnm: str, biyeok: str) -> str:
    b = biyeok.strip()
    if "앙상블" in b:
        return "앙상블"
    if any(k in b for k in ("스윙", "커버")):
        return "스윙"
    if prfnm in LEAD_SHOWS:
        return "주연"
    if prfnm in SUPPORT_SHOWS:
        return "조연"
    return "조연"


def parse_ymd(s: str) -> tuple[str, int]:
    """'YYYY.MM.DD' → ('YYYY-MM-DD', year)"""
    parts = s.strip().split(".")
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1]}-{parts[2]}", int(parts[0])
    return s.strip(), 0


def days_between(start: str, end: str) -> int:
    try:
        sy, sm, sd = map(int, start.split("."))
        ey, em, ed = map(int, end.split("."))
        return (date(ey, em, ed) - date(sy, sm, sd)).days + 1
    except Exception:
        return 0


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ── 공연 유형 (비고 → label) ─────────────────────────────────────────────────
def perf_type(bigo: str) -> str:
    b = bigo.strip()
    if "초연" in b:
        return "국내 초연"
    if "앙콜" in b:
        return "앙콜"
    if "연장" in b:
        return "연장"
    if "특별" in b:
        return "특별공연"
    return "정규"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manual_rows = load_csv(MANUAL_CSV)
    if not manual_rows:
        print(f"입력 파일 없음: {MANUAL_CSV}")
        return

    # ── 01 경력 타임라인 ──────────────────────────────────────────────────────
    timeline: list[dict] = []
    for seq, row in enumerate(manual_rows, 1):
        prfnm    = row["공연명"].strip()
        biyeok   = row.get("배역", "").strip()
        straw    = row["시작일"].strip()
        edraw    = row["종료일"].strip()
        start_iso, year = parse_ymd(straw)
        end_iso, _      = parse_ymd(edraw)
        bigo     = row.get("비고", "").strip()

        timeline.append({
            "seq":       seq,
            "공연명":     prfnm,
            "역할명":     biyeok,
            "역할구분":   classify_role(prfnm, biyeok),
            "공연유형":   perf_type(bigo),
            "시작일":     start_iso,
            "종료일":     end_iso,
            "연도":       year,
            "기간_일수":  days_between(straw, edraw),
            "장르":       row["장르"].strip(),
            "공연장":     row.get("공연장", "").strip(),
            "지역":       row.get("지역", "").strip() or "서울특별시",
            "제작사":     row.get("제작사", "").strip(),
            "비고":       bigo,
        })

    write_csv(OUT_DIR / "01_career_timeline.csv", [
        "seq", "공연명", "역할명", "역할구분", "공연유형",
        "시작일", "종료일", "연도", "기간_일수",
        "장르", "공연장", "지역", "제작사", "비고",
    ], timeline)
    print(f"01_career_timeline.csv  : {len(timeline)}행")

    # ── 02 공동출연 네트워크 ──────────────────────────────────────────────────
    # 모든 캐스트에서 서경수 출연 공연 ID 수집
    all_cast = load_csv(LEGACY_CAST) + load_csv(MAIN_CAST)
    seo_show_ids = {r["mt20id"] for r in all_cast if r.get("actor") == TARGET}

    # 공연 ID → 공연명 맵
    perf_name: dict[str, str] = {}
    for r in load_csv(LEGACY_PERF) + load_csv(MAIN_PERF):
        perf_name[r["mt20id"]] = r.get("prfnm", "")

    # 공동출연자별 공연 목록
    costar_shows: dict[str, set[str]] = defaultdict(set)
    for r in all_cast:
        mid = r["mt20id"]
        actor = r.get("actor", "").strip()
        if mid in seo_show_ids and actor and actor != TARGET:
            costar_shows[actor].add(mid)

    costar_rows: list[dict] = []
    for actor, show_ids in sorted(costar_shows.items(), key=lambda x: -len(x[1])):
        names = [perf_name.get(mid, mid) for mid in sorted(show_ids)]
        costar_rows.append({
            "공동출연_배우":  actor,
            "공동출연_횟수":  len(show_ids),
            "공동출연_작품":  ", ".join(names),
        })

    write_csv(OUT_DIR / "02_costar_network.csv",
              ["공동출연_배우", "공동출연_횟수", "공동출연_작품"],
              costar_rows)
    print(f"02_costar_network.csv   : {len(costar_rows)}명")

    # ── 03 캐릭터 그리드 ──────────────────────────────────────────────────────
    char_rows = [
        {
            "seq":      r["seq"],
            "공연명":   r["공연명"],
            "역할명":   r["역할명"],
            "역할구분": r["역할구분"],
            "공연유형": r["공연유형"],
            "연도":     r["연도"],
            "시작일":   r["시작일"],
            "장르":     r["장르"],
        }
        for r in timeline
        if r["역할구분"] not in ("앙상블", "스윙")
    ]
    write_csv(OUT_DIR / "03_characters.csv",
              ["seq", "공연명", "역할명", "역할구분", "공연유형", "연도", "시작일", "장르"],
              char_rows)
    print(f"03_characters.csv       : {len(char_rows)}개 역할")

    # ── 04 제작사 동선 ───────────────────────────────────────────────────────
    company_rows: list[dict] = []
    for r in timeline:
        for c in r["제작사"].split(","):
            c = c.strip()
            if c:
                company_rows.append({
                    "seq":     r["seq"],
                    "제작사":  c,
                    "공연명":  r["공연명"],
                    "연도":    r["연도"],
                    "시작일":  r["시작일"],
                    "역할구분": r["역할구분"],
                    "장르":    r["장르"],
                })
    write_csv(OUT_DIR / "04_companies.csv",
              ["seq", "제작사", "공연명", "연도", "시작일", "역할구분", "장르"],
              company_rows)
    print(f"04_companies.csv        : {len(company_rows)}건")

    # ── 요약 ─────────────────────────────────────────────────────────────────
    lead_n     = sum(1 for r in timeline if r["역할구분"] == "주연")
    support_n  = sum(1 for r in timeline if r["역할구분"] == "조연")
    ens_n      = sum(1 for r in timeline if r["역할구분"] in ("앙상블", "스윙"))
    years      = sorted({r["연도"] for r in timeline})
    companies  = {c.strip() for r in timeline for c in r["제작사"].split(",") if c.strip()}
    premieres  = sum(1 for r in timeline if r["공연유형"] == "국내 초연")

    print(f"\n{'─'*44}")
    print(f"  총 공연    : {len(timeline)}편  ({years[0]}~{years[-1]}, {len(years)}년)")
    print(f"  역할 분포  : 주연 {lead_n}편 / 조연 {support_n}편 / 앙상블·스윙 {ens_n}편")
    print(f"  국내 초연  : {premieres}편")
    print(f"  공동출연자 : {len(costar_rows)}명")
    print(f"  참여 제작사: {len(companies)}개")
    print(f"\n  저장 위치  : {OUT_DIR}/")


if __name__ == "__main__":
    main()
