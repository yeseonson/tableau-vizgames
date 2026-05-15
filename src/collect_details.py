"""
KOPIS 공연 상세 + 캐스트 병렬 수집 스크립트
collect.py와 동시에 실행 가능합니다.

동작 방식:
  1. performances.csv에서 mt20id 목록을 읽음
  2. performance_details.csv에 없는 ID만 API 호출
  3. 결과를 즉시 CSV에 한 줄씩 append
  4. 완료 후 performances.csv에 새 ID가 추가됐는지 POLL_INTERVAL초마다 재확인
  5. 새 ID가 없으면 종료
"""

import os
import csv
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ───────────────────────────────────────────────────────────────────
API_KEY      = os.environ["KOPIS_API_KEY"]
BASE_URL     = "http://www.kopis.or.kr/openApi/restful"
DELAY        = 0.3        # 초 (API 과부하 방지)
POLL_INTERVAL = 30        # 초 (performances.csv 재확인 주기)
OUTPUT_DIR   = Path(__file__).parent.parent / "data"

PERF_CSV    = OUTPUT_DIR / "performances.csv"
DETAIL_CSV  = OUTPUT_DIR / "performance_details.csv"
CAST_CSV    = OUTPUT_DIR / "cast.csv"

DETAIL_FIELDS = [
    "mt20id", "prfcast", "prfcrew",
    "entrpsnmS", "entrpsnmH", "entrpsnmP", "entrpsnmA",
    "pcseguidance", "dtguidance", "mt10id",
]
CAST_FIELDS = ["mt20id", "actor"]


# ── 유틸 ────────────────────────────────────────────────────────────────────
def load_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8-sig") as f:
        return {row[key] for row in csv.DictReader(f) if row.get(key)}


def open_csv(path: Path, fields: list[str]):
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    if is_new:
        writer.writeheader()
    return f, writer


# ── API ─────────────────────────────────────────────────────────────────────
def fetch_detail(mt20id: str, retries: int = 3) -> Optional[ET.Element]:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                f"{BASE_URL}/pblprfr/{mt20id}",
                params={"service": API_KEY},
                timeout=30,
            )
            r.raise_for_status()
            return ET.fromstring(r.content)
        except Exception as e:
            if attempt == retries:
                print(f"  [실패] {mt20id}: {e}")
                return None
            time.sleep(5 * attempt)
    return None


def parse_detail(root: ET.Element, mt20id: str) -> Optional[dict]:
    db = root.find(".//db")
    if db is None:
        return None
    return {
        "mt20id":       mt20id,
        "prfcast":      db.findtext("prfcast"),
        "prfcrew":      db.findtext("prfcrew"),
        "entrpsnmS":    db.findtext("entrpsnmS"),   # 기획사
        "entrpsnmH":    db.findtext("entrpsnmH"),   # 주최
        "entrpsnmP":    db.findtext("entrpsnmP"),   # 제작사
        "entrpsnmA":    db.findtext("entrpsnmA"),   # 후원
        "pcseguidance": db.findtext("pcseguidance"), # 티켓 가격
        "dtguidance":   db.findtext("dtguidance"),   # 공연 시간
        "mt10id":       db.findtext("mt10id"),       # 공연시설 ID
    }


# ── 배치 수집 ─────────────────────────────────────────────────────────────────
def collect_batch(todo: list[str], f_d, w_d, f_c, w_c, done: set[str]) -> int:
    """todo 목록의 상세 정보를 수집하고 즉시 저장. 저장된 건수 반환."""
    saved = 0
    total = len(todo)
    for i, mt20id in enumerate(todo, 1):
        root = fetch_detail(mt20id)
        if root:
            detail = parse_detail(root, mt20id)
            if detail:
                w_d.writerow(detail)
                f_d.flush()
                done.add(mt20id)
                saved += 1

                cast_str = detail.get("prfcast") or ""
                for actor in [a.strip() for a in cast_str.split(",") if a.strip()]:
                    w_c.writerow({"mt20id": mt20id, "actor": actor})
                f_c.flush()

        if i % 100 == 0:
            print(f"  {i}/{total} 완료 (저장 {saved}건)")
        time.sleep(DELAY)
    return saved


# ── 메인 ────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    if not PERF_CSV.exists():
        print(f"{PERF_CSV} 없음. collect.py를 먼저 실행하세요.")
        return

    done: set[str] = load_ids(DETAIL_CSV, "mt20id")
    print(f"기존 상세 {len(done)}건 확인\n")

    f_d, w_d = open_csv(DETAIL_CSV, DETAIL_FIELDS)
    f_c, w_c = open_csv(CAST_CSV, CAST_FIELDS)

    round_num = 0
    try:
        while True:
            round_num += 1
            all_ids = load_ids(PERF_CSV, "mt20id")
            todo = [i for i in all_ids if i not in done]

            if not todo:
                print(f"[round {round_num}] 수집할 신규 공연 없음. {POLL_INTERVAL}초 후 재확인...")
                # collect.py가 아직 실행 중일 수 있으므로 대기
                # 2회 연속 신규 없으면 종료
                if round_num > 1:
                    print("collect.py 완료 감지 → 종료")
                    break
                time.sleep(POLL_INTERVAL)
                continue

            print(f"[round {round_num}] 상세 수집: {len(todo)}건 (전체 {len(all_ids)}건 중)")
            saved = collect_batch(todo, f_d, w_d, f_c, w_c, done)
            print(f"[round {round_num}] 완료: {saved}건 저장\n")

            # 다음 라운드에서 performances.csv에 추가된 ID를 확인
            print(f"{POLL_INTERVAL}초 후 재확인...")
            time.sleep(POLL_INTERVAL)

    finally:
        f_d.close()
        f_c.close()

    detail_count = sum(1 for _ in open(DETAIL_CSV, encoding="utf-8-sig")) - 1
    cast_count   = sum(1 for _ in open(CAST_CSV,   encoding="utf-8-sig")) - 1
    print("\n=== 수집 완료 ===")
    print(f"  공연 상세: {detail_count:>6}건 → {DETAIL_CSV}")
    print(f"  캐스트:    {cast_count:>6}건 → {CAST_CSV}")


if __name__ == "__main__":
    main()
