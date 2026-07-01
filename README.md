# Subway Crowding Route

지하철 경로별 예상 탑승 시각을 계산하고, 구간별 혼잡도를 매칭해서 `덜 붐비는 경로`를 추천하는 프로젝트입니다.

## 현재 진행 상황

현재 구현된 범위는 아래와 같습니다.

- 최단경로 API 호출
  - 역명과 호선을 기준으로 최단경로 API를 호출합니다.
  - `min_time`, `min_transfer` 기준 경로 비교가 가능합니다.
- 실시간 도착정보 반영
  - 현재 시각과 다음 열차 도착 예정 초를 더해 실제 탑승 예상 시각을 계산합니다.
  - 실시간 도착정보 조회 실패 시 최단경로 스케줄의 첫 구간 출발 시각으로 ETA를 추정합니다.
- 경로 타임라인 생성
  - 최단경로 API의 구간별 이동시간과 대기시간을 누적합니다.
  - 각 구간별 예상 출발 시각, 예상 도착 시각, 누적 이동시간을 계산합니다.
  - 예상 통과 시각을 30분 단위 `time_slot`으로 내림 또는 반올림 처리할 수 있습니다.
  - 현재 날짜 기준으로 `평일/토요일/일요일` 타입을 계산합니다.
- 구간별 혼잡도 매칭
  - `day_type`, `line`, `station_name_norm`, `direction`, `time_slot` 기준으로 1차 매칭합니다.
  - 방향 표기가 다를 경우 direction mapper로 보정합니다.
  - 매칭 실패 시 같은 역의 가장 가까운 시간대 데이터를 우선 사용합니다.
  - 그것도 없으면 같은 호선 평균 혼잡도로 폴백합니다.
  - 구간별 `congestion`, `congestion_level`, `congestion_match_type`가 추가됩니다.
- 경로 혼잡도 요약
  - 구간 혼잡도를 이동시간 기준 가중평균으로 계산합니다.
  - 전체 경로의 최대 혼잡도도 함께 계산합니다.
  - 혼잡도 등급은 `여유 / 보통 / 주의 / 혼잡 / 매우 혼잡`으로 변환합니다.
- 경로 추천 점수
  - 최소 시간 경로와 최소 환승 경로를 비교합니다.
  - 추천 비용은 `소요시간 + 환승 penalty + 혼잡도 penalty + 매칭 실패 penalty + fallback penalty` 구조입니다.
  - 비용이 낮을수록 상위에 오도록 정렬합니다.
  - 최단 경로보다 시간이 조금 늘어나도 혼잡도가 충분히 낮으면 대체 경로를 제안합니다.
- 프론트 응답 변환
  - `ranked_routes`를 프론트에서 쓰기 쉬운 납작한 응답 형태로 변환합니다.
  - 경로 카드 렌더링에 필요한 핵심 필드만 바로 사용할 수 있습니다.
- SK 실시간 칸별 혼잡도 API 폴백 구조
  - 월 무료 호출 한도를 로컬 캐시로 관리합니다.
  - 한도 초과 또는 API 실패 시 실시간 API를 더 호출하지 않고 CSV 혼잡도로 자동 폴백합니다.

## 핵심 파일 설명

- [src/api_shortest_path.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/api_shortest_path.py)
  - 최단경로 API 호출, 역 코드 해석, 응답 정규화를 담당합니다.
- [src/realtime_arrival_api.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/realtime_arrival_api.py)
  - 실시간 도착정보를 조회하고 첫 구간에 탈 열차 ETA 후보를 고릅니다.
- [src/route_scorer.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/route_scorer.py)
  - 타임라인 생성, 혼잡도 요약, 추천 점수 계산, 경로 랭킹을 담당합니다.
- [src/congestion_matcher.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/congestion_matcher.py)
  - 타임라인 구간과 혼잡도 CSV를 매칭하고 경로 단위 요약을 계산합니다.
- [src/realtime_car_congestion_service.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/realtime_car_congestion_service.py)
  - SK 실시간 칸별 혼잡도 API 호출과 CSV 폴백 로직을 담당합니다.
- [src/validate_congestion_station_match.py](/C:/Users/AISW_203_113/Documents/GitHub/subway-crowding-route/subway-crowding-route/src/validate_congestion_station_match.py)
  - 혼잡도 데이터와 station master 매칭 상태를 검증합니다.

## 현재 추천 로직 요약

1. 현재 시각과 첫 열차 ETA로 예상 탑승 시각을 계산합니다.
2. 최단경로 구간별 이동시간과 대기시간을 누적해 timeline을 만듭니다.
3. 각 구간의 출발역 또는 대표역 기준으로 혼잡도를 조회합니다.
4. `day_type + line + station_name_norm + direction + time_slot`으로 1차 매칭합니다.
5. 실패하면 방향 보정, 근접 시간대, 같은 호선 평균 순서로 보완합니다.
6. 경로 전체에 대해 가중평균 혼잡도와 최대 혼잡도를 계산합니다.
7. 시간, 환승, 혼잡도를 함께 반영한 추천 비용으로 경로를 정렬합니다.

## 검증 결과

최근 검증 기준으로 아래는 확인되었습니다.

- `congestion_long.csv`와 `station_master.csv` 매칭률 100%
- 샘플 최단경로 JSON 기준 구간 혼잡도 매칭 정상 동작
- `강남 -> 서울대입구` 실제 API 호출 기준 타임라인 생성 및 혼잡도 매칭 정상 동작
- 실시간 도착정보 실패 시 최단경로 스케줄 기반 폴백 정상 동작
- SK 실시간 칸별 혼잡도 API는 한도 초과/실패 시 CSV 폴백 구조로 설계 완료

## 설치

의존성 설치:

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

## 환경변수

`.env` 또는 시스템 환경변수에 아래 값들을 설정합니다.

```env
SEOUL_METRO_KEY=...
SEOUL_API_KEY=...

# SK 실시간 칸별 혼잡도 API
SK_SUBWAY_CONGESTION_URL=...
SK_APP_KEY=...
SK_REALTIME_CONGESTION_MONTHLY_LIMIT=10
SK_REALTIME_CONGESTION_TIMEOUT=10
```

참고:

- `.env` 값 뒤에 `# 주석`이 붙어 있어도 현재 로더가 처리합니다.
- SK 실시간 API URL 패턴은 실제 명세가 확정되면 `SK_SUBWAY_CONGESTION_URL`에 반영하면 됩니다.

## 사용 예시

경로별 혼잡도 포함 결과 생성:

```python
from src.route_scorer import build_route_timeline_with_congestion_from_api

result = build_route_timeline_with_congestion_from_api(
    start_station_name="강남",
    end_station_name="서울대입구",
    start_line="2호선",
    end_line="2호선",
    route_type="min_time",
    search_dt="2026-07-01 08:30:00",
)
```

덜 붐비는 경로 랭킹 생성:

```python
from src.route_scorer import rank_least_crowded_routes, to_frontend_ranked_routes_response

ranked = rank_least_crowded_routes(
    start_station_name="강남",
    end_station_name="서울대입구",
    start_line="2호선",
    end_line="2호선",
    search_dt="2026-07-01 08:30:00",
)

frontend_payload = to_frontend_ranked_routes_response(ranked)
```

## 다음으로 볼 만한 작업

- 실제로 `min_time`과 `min_transfer`가 다른 O/D를 찾아 대체 경로 추천 케이스 검증
- SK 실시간 칸별 혼잡도 API의 실데이터 응답 형식 확정 후 필드 매핑 보완
- 프론트 화면에서 추천 사유와 혼잡도 레벨 배지 노출 연결
