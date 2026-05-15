"""
수동 입력 CSV → legacy 포맷 변환 스크립트

입력:  data/manual/seo_kyungsu_manual.csv
출력:  data/legacy/performances.csv, performance_details.csv, cast.csv 에 append

사용법:
    python3 src/import_manual.py [--dry-run] [--max-year YYYY]

    --max-year YYYY  시작일 연도가 YYYY 이하인 행만 임포트 (기본: 전체)
                     예) --max-year 2013  → 2006~2013 공연만 추가

컬럼 설명 (입력 CSV):
    공연명   (필수)
    장르     뮤지컬 | 연극
    시작일   YYYY.MM.DD
    종료일   YYYY.MM.DD
    공연장   (선택)
    지역     서울특별시, 경기도 등 (기본: 서울특별시)
    제작사   (선택)
    캐스트   쉼표 구분 ("서경수, 홍길동, ...")
    배역     서경수의 역할명 (선택, 참고용)
    비고     초연/앵콜 등 (선택, 참고용)
"""

import argparse
import csv
import sys
from pathlib import Path

INPUT_FILE = Path(__file__).parent.parent / "data" / "manual" / "seo_kyungsu_manual.csv"
LEGACY_DIR = Path(__file__).parent.parent / "data" / "legacy"

GENRE_CODE = {"뮤지컬": "GGGA", "연극": "AAAA"}
ID_PREFIX  = "MANUAL_"

PERF_FIELDS   = ["mt20id", "prfnm", "prfpdfrom", "prfpdto", "fcltynm",
                 "genrenm", "prfstate", "area", "openrun", "poster", "genre_code"]
DETAIL_FIELDS = ["mt20id", "prfcast", "prfcrew",
                 "entrpsnmS", "entrpsnmH", "entrpsnmP", "entrpsnmA",
                 "pcseguidance", "dtguidance", "mt10id"]
CAST_FIELDS   = ["mt20id", "actor"]


def load_existing_manual_ids(perf_path: Path) -> set[str]:
    if not perf_path.exists():
        return set()
    with open(perf_path, encoding="utf-8-sig") as f:
        return {r["mt20id"] for r in csv.DictReader(f) if r["mt20id"].startswith(ID_PREFIX)}


def next_id(existing_ids: set[str]) -> str:
    nums = {int(i.replace(ID_PREFIX, "")) for i in existing_ids if i.replace(ID_PREFIX, "").isdigit()}
    n = max(nums, default=0) + 1
    return f"{ID_PREFIX}{n:03d}"


def open_csv(path: Path, fields: list[str]):
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if is_new:
        w.writeheader()
    return f, w


def remove_manual_entries(legacy_dir: Path) -> None:
    """legacy CSV 파일에서 기존 MANUAL_ 항목을 모두 제거."""
    for fname in ["performances.csv", "performance_details.csv", "cast.csv"]:
        path = legacy_dir / fname
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if not r.get("mt20id", "").startswith(ID_PREFIX)]
            fieldnames = reader.fieldnames
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  [정리] {fname} MANUAL 항목 제거 완료")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 파싱 결과만 출력")
    parser.add_argument("--max-year", type=int, default=9999,
                        help="시작일 연도 상한 (기본: 전체). 예: --max-year 2013")
    parser.add_argument("--reset", action="store_true",
                        help="임포트 전 기존 MANUAL 항목 전체 제거")
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        print(f"입력 파일 없음: {INPUT_FILE}")
        sys.exit(1)

    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    perf_path   = LEGACY_DIR / "performances.csv"
    detail_path = LEGACY_DIR / "performance_details.csv"
    cast_path   = LEGACY_DIR / "cast.csv"

    if args.reset and not args.dry_run:
        print("기존 MANUAL 항목 제거 중...")
        remove_manual_entries(LEGACY_DIR)

    existing_ids = load_existing_manual_ids(perf_path)

    with open(INPUT_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # 연도 필터 적용
    def start_year(row: dict) -> int:
        try:
            return int(row.get("시작일", "0").split(".")[0])
        except ValueError:
            return 0

    filtered = [r for r in rows if start_year(r) <= args.max_year]
    skipped  = len(rows) - len(filtered)

    if args.dry_run:
        label = f"[DRY RUN] --max-year {args.max_year}" if args.max_year < 9999 else "[DRY RUN]"
        print(f"{label} 저장 없이 파싱 결과 출력 (총 {len(rows)}행 중 {len(filtered)}행 대상)\n")
    elif skipped:
        print(f"--max-year {args.max_year}: {skipped}행 건너뜀, {len(filtered)}행 처리\n")

    if not filtered:
        print("추가할 행이 없습니다.")
        return

    added = 0
    f_p, w_p = (None, None) if args.dry_run else open_csv(perf_path, PERF_FIELDS)
    f_d, w_d = (None, None) if args.dry_run else open_csv(detail_path, DETAIL_FIELDS)
    f_c, w_c = (None, None) if args.dry_run else open_csv(cast_path, CAST_FIELDS)

    try:
        for row in filtered:
            prfnm   = row["공연명"].strip()
            genrenm = row["장르"].strip()
            stdate  = row["시작일"].strip()
            eddate  = row["종료일"].strip()

            if not all([prfnm, genrenm, stdate, eddate]):
                print(f"  [건너뜀] 필수 항목 누락: {prfnm or '(공연명 없음)'}")
                continue

            genre_code = GENRE_CODE.get(genrenm)
            if not genre_code:
                print(f"  [건너뜀] 장르 오류 (뮤지컬/연극 중 하나): '{genrenm}' — {prfnm}")
                continue

            mid = next_id(existing_ids)
            existing_ids.add(mid)

            perf_row = {
                "mt20id":     mid,
                "prfnm":      prfnm,
                "prfpdfrom":  stdate,
                "prfpdto":    eddate,
                "fcltynm":    row.get("공연장", "").strip(),
                "genrenm":    genrenm,
                "prfstate":   "공연완료",
                "area":       row.get("지역", "서울특별시").strip() or "서울특별시",
                "openrun":    "N",
                "poster":     "",
                "genre_code": genre_code,
            }
            cast_str = row.get("캐스트", "").strip()
            detail_row = {
                "mt20id":       mid,
                "prfcast":      cast_str,
                "prfcrew":      "",
                "entrpsnmS":    "",
                "entrpsnmH":    "",
                "entrpsnmP":    row.get("제작사", "").strip(),
                "entrpsnmA":    "",
                "pcseguidance": "",
                "dtguidance":   "",
                "mt10id":       "",
            }
            actors = [a.strip() for a in cast_str.split(",") if a.strip()]
            biyeok = row.get("배역", "").strip()

            if args.dry_run:
                role_str = f" ({biyeok})" if biyeok else ""
                print(f"  → [{mid}] {prfnm}{role_str} ({stdate[:7]}~{eddate[:7]})")
                print(f"       캐스트: {actors}")
            else:
                w_p.writerow(perf_row)
                w_d.writerow(detail_row)
                for actor in actors:
                    w_c.writerow({"mt20id": mid, "actor": actor})
                role_str = f" ({biyeok})" if biyeok else ""
                print(f"  ✓ [{mid}] {prfnm}{role_str} ({stdate[:7]})")

            added += 1

    finally:
        if not args.dry_run:
            for fh in [f_p, f_d, f_c]:
                if fh:
                    fh.close()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}처리 완료: {added}건")
    if not args.dry_run and added:
        print(f"저장 위치: {LEGACY_DIR}/")


if __name__ == "__main__":
    main()
