## [Tableau] Viz Games Korea

### 서경수, 그가 도착한 무대

**[대시보드 바로가기](https://public.tableau.com/views/_17788074757220/Main)**

- **Timeline**: 50개 작품의 시간순 흐름
- **Costars**: 151명의 동료와의 협업
- **Characters**: 44개의 캐릭터

---

### 데이터

- **데이터 출처**: KOPIS OpenAPI + 위키/플레이DB 수작업 보완
- **수집 기간**: 2006–2026
- **장르 코드**: `GGGA`(뮤지컬), `AAAA`(연극)

### 파이프라인

1. **Collect** — Python으로 KOPIS OpenAPI 공연·출연진 데이터 수집
2. **Clean** — Pandas로 배우·작품·제작사 레코드 정규화 및 조인
3. **Visualize** — Tableau 대시보드로 타임라인·동료 관계·캐릭터 시각화

---

### 참가 인증서
![Certificate](2026%20VizGames%20Certificate%20of%20Participation.png)
