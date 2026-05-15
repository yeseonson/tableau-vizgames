"""
KOPIS 데이터 정제 스크립트
입력:  data/performances.csv, data/performance_details.csv, data/cast.csv
출력:  data/clean/
  - 01_performances.csv     : 공연 마스터 (날짜/기간 컬럼 추가)
  - 02_actor_productions.csv: 배우×공연 플랫 테이블 (Tableau 주력 테이블)
  - 03_actor_stats.csv      : 배우별 집계 (허브 분석용)
  - 04_company_stats.csv    : 제작사별 집계
  - 05_genre_cross.csv      : 뮤지컬↔연극 교차 배우 목록
  - 06_coappearance.csv     : 공동출연 쌍 (네트워크 엣지용, 활동 ≥5편 배우 한정)
"""

import re
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR  = DATA_DIR / "clean"
OUT_DIR.mkdir(exist_ok=True)

MUSICAL = "뮤지컬"
THEATER = "연극"


# ── 로드 ────────────────────────────────────────────────────────────────────
def load_raw() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    p = pd.read_csv(DATA_DIR / "performances.csv",       encoding="utf-8-sig")
    d = pd.read_csv(DATA_DIR / "performance_details.csv", encoding="utf-8-sig")
    c = pd.read_csv(DATA_DIR / "cast.csv",               encoding="utf-8-sig")
    return p, d, c


# ── 1. performances 정제 ─────────────────────────────────────────────────────
def clean_performances(p: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    # 상세 중복 제거 (collect.py + collect_details.py 동시 실행으로 2배 기록됨)
    d = d.drop_duplicates(subset="mt20id", keep="first")

    # 날짜 파싱
    p["prfpdfrom"] = pd.to_datetime(p["prfpdfrom"], format="%Y.%m.%d")
    p["prfpdto"]   = pd.to_datetime(p["prfpdto"],   format="%Y.%m.%d")

    # 시간 파생 컬럼
    p["year"]          = p["prfpdfrom"].dt.year
    p["month"]         = p["prfpdfrom"].dt.month
    p["quarter"]       = p["prfpdfrom"].dt.quarter
    p["year_month"]    = p["prfpdfrom"].dt.to_period("M").astype(str)
    p["duration_days"] = (p["prfpdto"] - p["prfpdfrom"]).dt.days + 1

    # area null → '기타'
    p["area"] = p["area"].fillna("기타")

    # 상세 조인 (기획사·주최·제작사)
    detail_cols = ["mt20id", "entrpsnmS", "entrpsnmH", "entrpsnmP",
                   "pcseguidance", "dtguidance", "mt10id"]
    p = p.merge(d[detail_cols], on="mt20id", how="left")

    # 제작사(entrpsnmP) 첫 번째 값만 추출 (쉼표 구분 → primary)
    for col in ["entrpsnmS", "entrpsnmH", "entrpsnmP"]:
        p[f"{col}_primary"] = (
            p[col].fillna("")
                  .str.split(",")
                  .str[0]
                  .str.strip()
                  .replace("", pd.NA)
        )

    # 날짜 → ISO 문자열 (Tableau 호환)
    p["prfpdfrom"] = p["prfpdfrom"].dt.strftime("%Y-%m-%d")
    p["prfpdto"]   = p["prfpdto"].dt.strftime("%Y-%m-%d")

    return p


# ── 2. 배우×공연 플랫 테이블 ────────────────────────────────────────────────
def build_actor_productions(perf: pd.DataFrame, c: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "mt20id", "prfnm", "genrenm", "genre_code",
        "prfpdfrom", "prfpdto", "year", "month", "quarter", "year_month",
        "duration_days", "area", "fcltynm",
        "entrpsnmP_primary", "entrpsnmH_primary",
        "prfstate", "openrun",
    ]
    ap = c.merge(perf[keep], on="mt20id", how="left")

    # 배우 이름 정규화: 앞뒤 공백·괄호 설명 제거
    ap["actor"] = ap["actor"].str.strip()
    ap["actor"] = ap["actor"].str.replace(r"\s*[\(\（].*?[\)\）]", "", regex=True).str.strip()
    ap = ap[ap["actor"] != ""]

    return ap


# ── 3. 배우 통계 ─────────────────────────────────────────────────────────────
def build_actor_stats(ap: pd.DataFrame) -> pd.DataFrame:
    g = ap.groupby("actor")

    stats = pd.DataFrame({
        "total_productions": g["mt20id"].nunique(),
        "musical_count":     g.apply(lambda x: x[x["genrenm"] == MUSICAL]["mt20id"].nunique()),
        "theater_count":     g.apply(lambda x: x[x["genrenm"] == THEATER]["mt20id"].nunique()),
        "first_year":        g["year"].min(),
        "last_year":         g["year"].max(),
        "active_years":      g["year"].nunique(),
        "area_count":        g["area"].nunique(),
    }).reset_index()

    stats["musical_pct"]   = (stats["musical_count"] / stats["total_productions"] * 100).round(1)
    stats["theater_pct"]   = (stats["theater_count"] / stats["total_productions"] * 100).round(1)
    stats["is_cross_genre"] = (stats["musical_count"] > 0) & (stats["theater_count"] > 0)

    # 주력 장르
    stats["primary_genre"] = stats.apply(
        lambda r: "크로스" if r["is_cross_genre"] and abs(r["musical_pct"] - 50) < 20
                  else (MUSICAL if r["musical_count"] >= r["theater_count"] else THEATER),
        axis=1,
    )

    # 주력 제작사 (가장 많이 출연한 곳)
    top_company = (
        ap[ap["entrpsnmP_primary"].notna()]
        .groupby(["actor", "entrpsnmP_primary"])["mt20id"]
        .nunique()
        .reset_index()
        .sort_values("mt20id", ascending=False)
        .drop_duplicates("actor")
        .rename(columns={"entrpsnmP_primary": "top_company", "mt20id": "top_company_count"})
    )
    stats = stats.merge(top_company[["actor", "top_company", "top_company_count"]], on="actor", how="left")

    return stats.sort_values("total_productions", ascending=False)


# ── 4. 제작사 통계 ───────────────────────────────────────────────────────────
def build_company_stats(perf: pd.DataFrame) -> pd.DataFrame:
    # entrpsnmP(제작사) 쉼표 구분 → 행 분리
    rows = []
    for _, row in perf.iterrows():
        companies_raw = str(row.get("entrpsnmP", "") or "")
        companies = [c.strip() for c in companies_raw.split(",") if c.strip()]
        if not companies:
            companies = ["(미상)"]
        for comp in companies:
            rows.append({
                "company":    comp,
                "mt20id":     row["mt20id"],
                "genrenm":    row["genrenm"],
                "year":       row["year"],
                "area":       row["area"],
                "prfstate":   row["prfstate"],
            })
    flat = pd.DataFrame(rows)

    stats = (
        flat.groupby("company")
        .agg(
            total_productions  = ("mt20id",  "nunique"),
            musical_count      = ("genrenm", lambda x: (x == MUSICAL).sum()),
            theater_count      = ("genrenm", lambda x: (x == THEATER).sum()),
            first_year         = ("year",    "min"),
            last_year          = ("year",    "max"),
            area_count         = ("area",    "nunique"),
        )
        .reset_index()
        .sort_values("total_productions", ascending=False)
    )
    stats["musical_pct"] = (stats["musical_count"] / stats["total_productions"] * 100).round(1)
    return stats[stats["company"] != "(미상)"]


# ── 5. 장르 교차 배우 ────────────────────────────────────────────────────────
def build_genre_cross(ap: pd.DataFrame, actor_stats: pd.DataFrame) -> pd.DataFrame:
    cross_actors = actor_stats[actor_stats["is_cross_genre"]]["actor"].tolist()
    cross = ap[ap["actor"].isin(cross_actors)].copy()

    # 연도별 장르별 출연 수
    cross_yearly = (
        cross.groupby(["actor", "year", "genrenm"])["mt20id"]
        .nunique()
        .reset_index()
        .rename(columns={"mt20id": "prod_count"})
    )
    # 배우 통계 붙이기
    cross_yearly = cross_yearly.merge(
        actor_stats[["actor", "total_productions", "musical_count",
                     "theater_count", "musical_pct", "primary_genre"]],
        on="actor", how="left",
    )
    return cross_yearly


# ── 6. 공동출연 쌍 (네트워크 엣지) ─────────────────────────────────────────
def build_coappearance(ap: pd.DataFrame, actor_stats: pd.DataFrame,
                       min_productions: int = 5) -> pd.DataFrame:
    # 활발한 배우만 대상 (네트워크 규모 제어)
    active = actor_stats[actor_stats["total_productions"] >= min_productions]["actor"].tolist()
    filtered = ap[ap["actor"].isin(active)][["mt20id", "actor"]]

    # 같은 공연에 출연한 배우 쌍 생성
    merged = filtered.merge(filtered, on="mt20id", suffixes=("_a", "_b"))
    merged = merged[merged["actor_a"] < merged["actor_b"]]  # 중복 쌍 제거

    pairs = (
        merged.groupby(["actor_a", "actor_b"])["mt20id"]
        .nunique()
        .reset_index()
        .rename(columns={"mt20id": "shared_productions"})
        .sort_values("shared_productions", ascending=False)
    )

    # 배우 통계 조인 (시각화 노드 속성용)
    for side in ["a", "b"]:
        pairs = pairs.merge(
            actor_stats[["actor", "total_productions", "primary_genre"]].rename(
                columns={
                    "actor":             f"actor_{side}",
                    "total_productions": f"total_{side}",
                    "primary_genre":     f"genre_{side}",
                }
            ),
            on=f"actor_{side}", how="left",
        )

    return pairs[pairs["shared_productions"] >= 2]  # 1편만 공동출연은 제외


# ── 메인 ────────────────────────────────────────────────────────────────────
def main():
    print("데이터 로드 중...")
    p_raw, d_raw, c_raw = load_raw()
    print(f"  performances: {len(p_raw):,}행  |  details: {len(d_raw):,}행  |  cast: {len(c_raw):,}행")

    print("\n01 공연 마스터 정제...")
    perf = clean_performances(p_raw, d_raw)
    perf.to_csv(OUT_DIR / "01_performances.csv", index=False, encoding="utf-8-sig")
    print(f"  → {len(perf):,}행 저장")

    print("\n02 배우×공연 플랫 테이블...")
    ap = build_actor_productions(perf, c_raw)
    ap.to_csv(OUT_DIR / "02_actor_productions.csv", index=False, encoding="utf-8-sig")
    print(f"  → {len(ap):,}행 저장")

    print("\n03 배우 통계...")
    actor_stats = build_actor_stats(ap)
    actor_stats.to_csv(OUT_DIR / "03_actor_stats.csv", index=False, encoding="utf-8-sig")
    print(f"  → {len(actor_stats):,}행 저장")

    print("\n04 제작사 통계...")
    company_stats = build_company_stats(perf)
    company_stats.to_csv(OUT_DIR / "04_company_stats.csv", index=False, encoding="utf-8-sig")
    print(f"  → {len(company_stats):,}행 저장")

    print("\n05 장르 교차 배우...")
    cross = build_genre_cross(ap, actor_stats)
    cross.to_csv(OUT_DIR / "05_genre_cross.csv", index=False, encoding="utf-8-sig")
    cross_count = actor_stats["is_cross_genre"].sum()
    print(f"  → 교차 배우 {cross_count:,}명, {len(cross):,}행 저장")

    print("\n06 공동출연 네트워크 엣지 (≥5편 배우)...")
    coapp = build_coappearance(ap, actor_stats, min_productions=5)
    coapp.to_csv(OUT_DIR / "06_coappearance.csv", index=False, encoding="utf-8-sig")
    print(f"  → {len(coapp):,}쌍 저장")

    print(f"\n완료! → {OUT_DIR}/")
    print("\n[Tableau 연결 순서]")
    print("  1) 01_performances.csv        — 공연 마스터 (mt20id PK)")
    print("  2) 02_actor_productions.csv   — 배우×공연 (actor + mt20id)")
    print("  3) 03_actor_stats.csv         — 배우 노드 속성 (actor PK)")
    print("  4) 04_company_stats.csv       — 제작사 집계")
    print("  5) 05_genre_cross.csv         — 장르 교차 타임라인")
    print("  6) 06_coappearance.csv        — 네트워크 엣지 (actor_a / actor_b)")


if __name__ == "__main__":
    main()
