"""
KOPIS 공연시설 상세 API를 이용해 data/clean/01_performances.csv의
고유 공연시설(mt10id) 주소(adres)를 조회하고 컬럼을 추가합니다.

출력: data/clean/01_performances.csv (adres 컬럼 추가)
중간 캐시: data/venue_adres.csv (mt10id → adres)
"""

import os
import csv
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.environ["KOPIS_API_KEY"]
BASE_URL = "http://www.kopis.or.kr/openApi/restful"
DELAY    = 0.3

DATA_DIR   = Path(__file__).parent.parent / "data"
PERF_PATH  = DATA_DIR / "clean" / "01_performances.csv"
CACHE_PATH = DATA_DIR / "venue_adres.csv"
CACHE_FIELDS = ["mt10id", "adres", "la", "lo"]


def fetch_venue(mt10id: str) -> dict:
    try:
        r = requests.get(
            f"{BASE_URL}/prfplc/{mt10id}",
            params={"service": API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        db = root.find(".//db")
        if db is None:
            return {"adres": "", "la": "", "lo": ""}
        return {
            "adres": (db.findtext("adres") or "").strip(),
            "la":    (db.findtext("la")    or "").strip(),
            "lo":    (db.findtext("lo")    or "").strip(),
        }
    except Exception as e:
        print(f"  [경고] {mt10id}: {e}")
        return {"adres": "", "la": "", "lo": ""}


def load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, encoding="utf-8-sig") as f:
        return {r["mt10id"]: {"adres": r["adres"], "la": r["la"], "lo": r["lo"]}
                for r in csv.DictReader(f)}


def main():
    import pandas as pd

    df = pd.read_csv(PERF_PATH, encoding="utf-8-sig")
    venues = df[["fcltynm", "mt10id"]].drop_duplicates("mt10id")
    print(f"고유 시설 {len(venues)}개")

    cache = load_cache()
    todo = venues[~venues["mt10id"].isin(cache)]["mt10id"].tolist()
    print(f"조회 필요: {len(todo)}개 (캐시 {len(cache)}개)")

    with open(CACHE_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        if not cache:
            writer.writeheader()
        for i, mt10id in enumerate(todo, 1):
            info = fetch_venue(mt10id)
            cache[mt10id] = info
            writer.writerow({"mt10id": mt10id, **info})
            f.flush()
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} 완료")
            time.sleep(DELAY)

    df["adres"] = df["mt10id"].map(lambda x: cache.get(x, {}).get("adres", "")).fillna("")
    df["la"]    = df["mt10id"].map(lambda x: cache.get(x, {}).get("la", "")).fillna("")
    df["lo"]    = df["mt10id"].map(lambda x: cache.get(x, {}).get("lo", "")).fillna("")
    df.to_csv(PERF_PATH, index=False, encoding="utf-8-sig")
    print(f"\n완료: adres/la/lo 컬럼 추가 → {PERF_PATH}")
    print(f"주소 없음: {(df['adres'] == '').sum()}건")


if __name__ == "__main__":
    main()
