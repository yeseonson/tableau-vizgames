"""
KOPIS OpenAPI 데이터 수집 스크립트
수집 대상: 뮤지컬(GGGA), 연극(AAAA)
수집 기간: 2021.01.01 ~ 2026.04.30
출력 파일: data/performances.csv, data/performance_details.csv, data/cast.csv

월별로 쿼리를 분할하여 API 페이지 제한을 우회하고,
수집 즉시 CSV에 한 줄씩 append하여 중단 시에도 데이터를 보존합니다.
"""

import os
import csv
import time
import calendar
import requests
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Iterator, Optional
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ───────────────────────────────────────────────────────────────────
API_KEY     = os.environ["KOPIS_API_KEY"]
BASE_URL    = "http://www.kopis.or.kr/openApi/restful"
GENRES      = {"GGGA": "뮤지컬", "AAAA": "연극"}
START_YEAR  = 2021
START_MONTH = 1
END_YEAR    = 2026
END_MONTH   = 4
ROWS        = 100
DELAY       = 0.3   # 초
OUTPUT_DIR  = Path(__file__).parent.parent / "data"

# ── CSV 헤더 ────────────────────────────────────────────────────────────────
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
    """(stdate, eddate) 형식의 월별 기간 생성기."""
    y, m = START_YEAR, START_MONTH
    while (y, m) <= (END_YEAR, END_MONTH):
        last_day = calendar.monthrange(y, m)[1]
        yield f"{y}{m:02d}01", f"{y}{m:02d}{last_day:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


# ── API 호출 (재시도 포함) ────────────────────────────────────────────────────
def _get_with_retry(url: str, params: dict, retries: int = 3) -> requests.Response:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            if attempt == retries:
                raise
            wait = 5 * attempt
            print(f"  [재시도 {attempt}/{retries}] {e} — {wait}초 대기")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def get_list_page(genre: str, stdate: str, eddate: str, page: int) -> ET.Element:
    r = _get_with_retry(f"{BASE_URL}/pblprfr", {
        "service": API_KEY, "stdate": stdate, "eddate": eddate,
        "shcate": genre, "rows": ROWS, "cpage": page,
    })
    return ET.fromstring(r.content)


def get_detail(mt20id: str) -> Optional[ET.Element]:
    r = _get_with_retry(f"{BASE_URL}/pblprfr/{mt20id}", {"service": API_KEY})
    return ET.fromstring(r.content)


# ── 파싱 ────────────────────────────────────────────────────────────────────
def parse_list(root: ET.Element, genre_code: str) -> list[dict]:
    rows = []
    for db in root.findall(".//db"):
        rows.append({
            "mt20id":    db.findtext("mt20id"),
            "prfnm":     db.findtext("prfnm"),
            "prfpdfrom": db.findtext("prfpdfrom"),
            "prfpdto":   db.findtext("prfpdto"),
            "fcltynm":   db.findtext("fcltynm"),
            "genrenm":   db.findtext("genrenm"),
            "prfstate":  db.findtext("prfstate"),
            "area":      db.findtext("area"),
            "openrun":   db.findtext("openrun"),
            "poster":    db.findtext("poster"),
            "genre_code": genre_code,
        })
    return rows


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
    """파일이 없으면 헤더 포함 신규 생성, 있으면 append 모드로 열기."""
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if is_new:
        writer.writeheader()
    return f, writer


def load_seen_ids(path: Path, key: str) -> set[str]:
    """이미 수집된 ID를 읽어 중복 수집 방지."""
    if not path.exists():
        return set()
    seen = set()
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get(key):
                seen.add(row[key])
    return seen


# ── 1단계: 공연 목록 수집 ──────────────────────────────────────────────────
def collect_performances(out: Path) -> list[str]:
    seen = load_seen_ids(out, "mt20id")
    print(f"기존 공연 {len(seen)}건 확인 (중복 제외)")

    f, writer = open_csv(out, PERF_FIELDS)
    total_new = 0
    try:
        for genre_code, label in GENRES.items():
            for stdate, eddate in months():
                page = 1
                month_new = 0
                while True:
                    try:
                        root = get_list_page(genre_code, stdate, eddate, page)
                    except Exception as e:
                        print(f"  [건너뜀] [{label}] {stdate[:6]} page {page}: {e}")
                        break
                    rows = parse_list(root, genre_code)
                    if not rows:
                        break
                    for row in rows:
                        if row["mt20id"] not in seen:
                            writer.writerow(row)
                            f.flush()
                            seen.add(row["mt20id"])
                            month_new += 1
                    if len(rows) < ROWS:
                        break
                    page += 1
                    time.sleep(DELAY)
                if month_new:
                    print(f"  [{label}] {stdate[:6]}: +{month_new}건")
                total_new += month_new
    finally:
        f.close()

    print(f"\n공연 목록 완료: 신규 {total_new}건 → {out}\n")
    return list(seen)


# ── 2단계: 공연 상세 수집 ──────────────────────────────────────────────────
def collect_details(mt20ids: list[str], out: Path) -> None:
    seen = load_seen_ids(out, "mt20id")
    todo = [i for i in mt20ids if i not in seen]
    print(f"공연 상세 수집: {len(todo)}건 (이미 {len(seen)}건 완료)")

    f_d, w_d = open_csv(out, DETAIL_FIELDS)
    cast_path = out.parent / "cast.csv"
    f_c, w_c = open_csv(cast_path, CAST_FIELDS)

    try:
        for i, mt20id in enumerate(todo, 1):
            try:
                root = get_detail(mt20id)
                detail = parse_detail(root, mt20id)
                if detail:
                    w_d.writerow(detail)
                    f_d.flush()
                    cast_str = detail.get("prfcast") or ""
                    for actor in [a.strip() for a in cast_str.split(",") if a.strip()]:
                        w_c.writerow({"mt20id": mt20id, "actor": actor})
                    f_c.flush()
            except Exception as e:
                print(f"  [경고] {mt20id} 실패: {e}")
            if i % 200 == 0 or i == len(todo):
                print(f"  상세 {i}/{len(todo)} 완료")
            time.sleep(DELAY)
    finally:
        f_d.close()
        f_c.close()

    print(f"공연 상세 완료 → {out}")
    print(f"캐스트 완료   → {cast_path}\n")


# ── 메인 ────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    perf_path   = OUTPUT_DIR / "performances.csv"
    detail_path = OUTPUT_DIR / "performance_details.csv"

    mt20ids = collect_performances(perf_path)
    collect_details(mt20ids, detail_path)

    print("=== 수집 완료 ===")


if __name__ == "__main__":
    main()
