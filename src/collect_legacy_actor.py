"""
2006–2020 KOPIS 데이터 중 특정 배우 출연 공연만 수집.

동작:
  1. 월별 공연 목록 API로 공연 ID 수집
  2. 각 ID의 상세 API를 호출해 cast에 TARGET_ACTOR가 있으면 저장
  3. data/legacy/ 에 performances.csv / performance_details.csv / cast.csv 저장
  4. already_checked.txt로 중단 후 재개 가능

주의: 전체 공연 상세를 호출하므로 공연 수에 따라 1~3시간 소요될 수 있습니다.
"""

import os
import csv
import time
import calendar
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, Optional
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────────
API_KEY      = os.environ["KOPIS_API_KEY"]
BASE_URL     = "http://www.kopis.or.kr/openApi/restful"
GENRES       = {"GGGA": "뮤지컬", "AAAA": "연극"}
START_YEAR   = 2009  # KOPIS에 2008년 이전 데이터 거의 없음
END_YEAR     = 2020
ROWS         = 100
DELAY        = 0.3          # 초 (API 과부하 방지)
TARGET_ACTOR = "서경수"
OUTPUT_DIR   = Path(__file__).parent.parent / "data" / "legacy"

PERF_FIELDS = [
    "mt20id", "prfnm", "prfpdfrom", "prfpdto", "fcltynm",
    "genrenm", "prfstate", "area", "openrun", "poster", "genre_code",
]
DETAIL_FIELDS = [
    "mt20id", "prfcast", "prfcrew",
    "entrpsnmS", "entrpsnmH", "entrpsnmP", "entrpsnmA",
    "pcseguidance", "dtguidance", "mt10id",
]
CAST_FIELDS = ["mt20id", "actor"]


# ── 날짜 유틸 ────────────────────────────────────────────────────────────────
def months() -> Iterator[tuple[str, str]]:
    y, m = START_YEAR, 1
    while (y, m) <= (END_YEAR, 12):
        last_day = calendar.monthrange(y, m)[1]
        yield f"{y}{m:02d}01", f"{y}{m:02d}{last_day:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


# ── API 호출 ─────────────────────────────────────────────────────────────────
def _get_with_retry(url: str, params: dict, retries: int = 3) -> requests.Response:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            if attempt == retries:
                raise
            time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def get_list_page(genre: str, stdate: str, eddate: str, page: int) -> ET.Element:
    r = _get_with_retry(f"{BASE_URL}/pblprfr", {
        "service": API_KEY, "stdate": stdate, "eddate": eddate,
        "shcate": genre, "rows": ROWS, "cpage": page,
    })
    return ET.fromstring(r.content)


def fetch_detail(mt20id: str) -> Optional[ET.Element]:
    try:
        r = _get_with_retry(f"{BASE_URL}/pblprfr/{mt20id}", {"service": API_KEY})
        return ET.fromstring(r.content)
    except Exception as e:
        print(f"  [실패] {mt20id}: {e}")
        return None


# ── 파싱 ─────────────────────────────────────────────────────────────────────
def parse_list_row(db: ET.Element, genre_code: str) -> dict:
    return {
        "mt20id":     db.findtext("mt20id"),
        "prfnm":      db.findtext("prfnm"),
        "prfpdfrom":  db.findtext("prfpdfrom"),
        "prfpdto":    db.findtext("prfpdto"),
        "fcltynm":    db.findtext("fcltynm"),
        "genrenm":    db.findtext("genrenm"),
        "prfstate":   db.findtext("prfstate"),
        "area":       db.findtext("area"),
        "openrun":    db.findtext("openrun"),
        "poster":     db.findtext("poster"),
        "genre_code": genre_code,
    }


def parse_detail(root: ET.Element, mt20id: str) -> Optional[dict]:
    db = root.find(".//db")
    if db is None:
        return None
    return {
        "mt20id":       mt20id,
        "prfcast":      db.findtext("prfcast"),
        "prfcrew":      db.findtext("prfcrew"),
        "entrpsnmS":    db.findtext("entrpsnmS"),
        "entrpsnmH":    db.findtext("entrpsnmH"),
        "entrpsnmP":    db.findtext("entrpsnmP"),
        "entrpsnmA":    db.findtext("entrpsnmA"),
        "pcseguidance": db.findtext("pcseguidance"),
        "dtguidance":   db.findtext("dtguidance"),
        "mt10id":       db.findtext("mt10id"),
    }


# ── CSV 헬퍼 ─────────────────────────────────────────────────────────────────
def open_csv(path: Path, fields: list[str]):
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if is_new:
        w.writeheader()
    return f, w


def load_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.open(encoding="utf-8") if line.strip()}


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    perf_path    = OUTPUT_DIR / "performances.csv"
    detail_path  = OUTPUT_DIR / "performance_details.csv"
    cast_path    = OUTPUT_DIR / "cast.csv"
    checked_path = OUTPUT_DIR / "already_checked.txt"  # 상세 호출 완료 ID (재개용)

    already_checked = load_set(checked_path)
    print(f"[재개] 이미 처리된 공연 ID: {len(already_checked):,}건")

    matched_ids: set[str] = set()
    if perf_path.exists():
        with open(perf_path, encoding="utf-8-sig") as f:
            matched_ids = {row["mt20id"] for row in csv.DictReader(f) if row.get("mt20id")}
    print(f"[재개] 이미 저장된 '{TARGET_ACTOR}' 출연 공연: {len(matched_ids):,}건\n")

    f_p, w_p = open_csv(perf_path, PERF_FIELDS)
    f_d, w_d = open_csv(detail_path, DETAIL_FIELDS)
    f_c, w_c = open_csv(cast_path, CAST_FIELDS)
    f_checked = open(checked_path, "a", encoding="utf-8")

    total_checked = 0
    total_matched = len(matched_ids)

    try:
        for genre_code, label in GENRES.items():
            for stdate, eddate in months():
                page = 1
                while True:
                    try:
                        root = get_list_page(genre_code, stdate, eddate, page)
                    except Exception as e:
                        print(f"  [건너뜀] [{label}] {stdate[:6]} p{page}: {e}")
                        break

                    dbs = root.findall(".//db")
                    if not dbs:
                        break

                    for db in dbs:
                        mid = db.findtext("mt20id")
                        if not mid or mid in already_checked:
                            continue

                        detail_root = fetch_detail(mid)
                        total_checked += 1

                        if detail_root:
                            detail = parse_detail(detail_root, mid)
                            if detail:
                                cast_str = detail.get("prfcast") or ""
                                actors = [a.strip() for a in cast_str.split(",") if a.strip()]
                                if TARGET_ACTOR in actors and mid not in matched_ids:
                                    total_matched += 1
                                    matched_ids.add(mid)
                                    perf_row = parse_list_row(db, genre_code)
                                    w_p.writerow(perf_row)
                                    f_p.flush()
                                    w_d.writerow(detail)
                                    f_d.flush()
                                    for actor in actors:
                                        w_c.writerow({"mt20id": mid, "actor": actor})
                                    f_c.flush()
                                    print(
                                        f"  ★ [{label}] {db.findtext('prfnm')} "
                                        f"({db.findtext('prfpdfrom', '')[:7]}) "
                                        f"— {TARGET_ACTOR} 출연 확인! (누적 {total_matched}건)"
                                    )

                        f_checked.write(mid + "\n")
                        f_checked.flush()
                        already_checked.add(mid)
                        time.sleep(DELAY)

                    if len(dbs) < ROWS:
                        break
                    page += 1
                    time.sleep(DELAY)

                # 월별 진행 상황 출력
                if total_checked > 0 and total_checked % 300 == 0:
                    print(f"  진행 {total_checked:,}건 처리 | {total_matched}건 매칭 | 현재: {stdate[:6]} {label}")

    finally:
        f_p.close()
        f_d.close()
        f_c.close()
        f_checked.close()

    print("\n=== 수집 완료 ===")
    print(f"  총 처리: {total_checked:,}건 (이번 실행)")
    print(f"  '{TARGET_ACTOR}' 출연 공연: {total_matched:,}건")
    print(f"  저장 위치: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
