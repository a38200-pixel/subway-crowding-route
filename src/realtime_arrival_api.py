"""실시간 도착정보 API를 조회하고 첫 구간 탑승 ETA 후보를 고르는 모듈."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

from src.api_shortest_path import fetch_shortest_path_by_name, load_station_master


BASE_DIR = Path.cwd()
ENV_PATH = BASE_DIR / ".env"
NO_PROXY_OPENER = build_opener(ProxyHandler({}))


# .env 파일을 읽어 실시간 도착 API 키를 환경변수에 적재한다.
def load_env_file(env_path: Path = ENV_PATH) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # Support inline comments in .env like:
        # SEOUL_API_KEY=xxxxx  # comment
        if value and value[0] not in {"'", '"'} and " #" in value:
            value = value.split(" #", 1)[0].rstrip()

        value = value.strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


# 실시간 도착 API 키를 환경변수에서 읽어온다.
def get_realtime_api_key() -> str:
    load_env_file()
    api_key = (os.getenv("SEOUL_API_KEY") or os.getenv("SEOUL_SUBWAY_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("SEOUL_API_KEY is not set.")
    return api_key


# 출발역과 호선 기준으로 실시간 도착 API 조회에 필요한 역 컨텍스트를 찾는다.
def resolve_departure_station_for_arrival(
    station_name: str,
    *,
    line: str,
    station_rows: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    rows = station_rows if station_rows is not None else load_station_master()
    target = [
        row for row in rows
        if row.get("station_name_norm", "").strip() == station_name.strip()
        and row.get("line", "").strip() == line.strip()
    ]

    if not target:
        raise ValueError(f"Station not found for realtime arrival: {line} {station_name}")

    row = target[0]
    api_station_name = row.get("api_station_name", "").strip()
    subway_id = row.get("subway_id", "").strip()
    if not api_station_name:
        raise ValueError(f"api_station_name is missing for {line} {station_name}")
    if not subway_id:
        raise ValueError(f"subway_id is missing for {line} {station_name}")

    return {
        "line": row.get("line", "").strip(),
        "subway_id": subway_id,
        "station_name": row.get("station_name", "").strip(),
        "station_name_norm": row.get("station_name_norm", "").strip(),
        "api_station_name": api_station_name,
    }


# subway_id를 호선명으로 역매핑하기 위한 사전을 만든다.
def build_subway_id_line_map(station_rows: list[dict[str, str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in station_rows:
        subway_id = row.get("subway_id", "").strip()
        line = row.get("line", "").strip()
        if subway_id and line and subway_id not in mapping:
            mapping[subway_id] = line
    return mapping


# 서울 열린데이터 실시간 도착 API를 호출한다.
def call_realtime_arrival(api_station_name: str, start: int = 0, end: int = 10) -> dict[str, Any]:
    api_key = get_realtime_api_key()
    encoded_station_name = quote(api_station_name, safe="")
    request_url = (
        f"http://swopenapi.seoul.go.kr/api/subway/"
        f"{api_key}/json/realtimeStationArrival/"
        f"{start}/{end}/{encoded_station_name}"
    )

    with NO_PROXY_OPENER.open(request_url, timeout=15) as response:
        body_text = response.read().decode("utf-8", errors="replace")

    return json.loads(body_text)


# API 수신 시각 문자열을 datetime으로 파싱한다.
def _parse_recptn_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# 값이 비정상이면 None을 반환하는 정수 파서다.
def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ETA 초 값을 사람이 읽기 쉬운 문자열로 바꾼다.
def _format_eta(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds <= 0:
        return "곧 도착"
    minutes, remain = divmod(seconds, 60)
    if minutes == 0:
        return f"{remain}초"
    if remain == 0:
        return f"{minutes}분"
    return f"{minutes}분 {remain}초"


# 열차 행선 문자열에서 종착역 부분만 추출한다.
def _extract_destination(train_line_name: str | None) -> str | None:
    if not train_line_name:
        return None
    return train_line_name.split(" - ", 1)[0].strip()


# 실시간 도착 원본 행을 앱에서 쓰는 공통 형태로 정규화한다.
def normalize_realtime_arrival_item(
    item: dict[str, Any],
    *,
    fallback_line: str,
    line_name_map: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    recptn_dt_text = item.get("recptnDt")
    recptn_dt = _parse_recptn_dt(recptn_dt_text)
    base_arrival_seconds = _safe_int(item.get("barvlDt"))
    adjusted_arrival_seconds = base_arrival_seconds
    subway_id = str(item.get("subwayId", "")).strip()
    resolved_line = (
        (line_name_map or {}).get(subway_id)
        or str(item.get("subwayNm", "")).strip()
        or fallback_line
    )

    if base_arrival_seconds is not None and recptn_dt is not None:
        age_seconds = max(int((now - recptn_dt).total_seconds()), 0)
        adjusted_arrival_seconds = max(base_arrival_seconds - age_seconds, 0)

    return {
        "line": resolved_line,
        "subway_id": subway_id,
        "direction": str(item.get("updnLine", "")).strip(),
        "destination": _extract_destination(item.get("trainLineNm")),
        "train_line_name": item.get("trainLineNm"),
        "arrival_message": item.get("arvlMsg2"),
        "arrival_station_hint": item.get("arvlMsg3"),
        "arrival_eta_seconds": adjusted_arrival_seconds,
        "arrival_eta_text": _format_eta(adjusted_arrival_seconds),
        "recptnDt": recptn_dt_text,
        "train_no": item.get("btrainNo"),
        "terminal_station": item.get("bstatnNm"),
        "raw": item,
    }


# 첫 구간의 호선과 방향에 맞는 도착정보만 남긴다.
def filter_arrivals_for_first_segment(
    arrivals: list[dict[str, Any]],
    *,
    subway_id: str,
    line: str,
    direction: str | None,
) -> list[dict[str, Any]]:
    filtered = [
        item for item in arrivals
        if item.get("subway_id") == subway_id and item.get("line") == line
    ]

    if direction:
        filtered = [item for item in filtered if item.get("direction") == direction]

    return filtered


# ETA 기준으로 가장 빠른 도착 후보 n개를 고른다.
def select_fastest_arrivals(arrivals: list[dict[str, Any]], limit: int = 2) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        eta = item.get("arrival_eta_seconds")
        return (eta if isinstance(eta, int) else 10**9, str(item.get("train_no", "")))

    return sorted(arrivals, key=sort_key)[:limit]


# 최단경로 첫 구간에 실제로 탈 수 있는 실시간 열차 도착 후보를 반환한다.
def get_realtime_arrivals_for_shortest_path(
    start_station_name: str,
    end_station_name: str,
    *,
    start_line: str | None = None,
    end_line: str | None = None,
    route_type: str = "min_time",
    search_dt: str | None = None,
    top_n: int = 2,
) -> dict[str, Any]:
    try:
        path_result = fetch_shortest_path_by_name(
            start_station_name=start_station_name,
            end_station_name=end_station_name,
            route_type=route_type,
            start_line=start_line,
            end_line=end_line,
            search_dt=search_dt,
        )
    except Exception as exc:
        return {
            "ok": False,
            "message": "경로 조회 실패",
            "error": str(exc),
            "shortest_path": None,
            "selected_arrivals": [],
        }

    if not path_result.get("ok"):
        return {
            "ok": False,
            "message": "경로 조회 실패",
            "error": path_result.get("error"),
            "shortest_path": path_result.get("normalized_response"),
            "selected_arrivals": [],
        }

    shortest_path = path_result.get("normalized_response") or {}
    segments = shortest_path.get("segments") or []
    if not segments:
        return {
            "ok": False,
            "message": "경로 조회 실패",
            "error": "No route segments found.",
            "shortest_path": shortest_path,
            "selected_arrivals": [],
        }

    first_segment = segments[0]
    first_line = str(first_segment.get("line") or "").strip()
    first_direction = str(first_segment.get("direction") or "").strip() or None

    station_rows = load_station_master()
    subway_id_line_map = build_subway_id_line_map(station_rows)
    try:
        station_info = resolve_departure_station_for_arrival(
            start_station_name,
            line=first_line,
            station_rows=station_rows,
        )
    except Exception as exc:
        return {
            "ok": False,
            "message": "실시간 도착정보 조회 실패",
            "error": str(exc),
            "shortest_path": shortest_path,
            "selected_arrivals": [],
        }

    try:
        raw_arrival_response = call_realtime_arrival(station_info["api_station_name"])
    except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "message": "실시간 도착정보 조회 실패",
            "error": str(exc),
            "shortest_path": shortest_path,
            "selected_arrivals": [],
        }

    error_message = raw_arrival_response.get("errorMessage", {})
    if isinstance(error_message, dict):
        result_code = str(error_message.get("code", "")).strip()
        if result_code and result_code != "INFO-000":
            return {
                "ok": False,
                "message": "실시간 도착정보 조회 실패",
                "error": error_message.get("message") or result_code,
                "shortest_path": shortest_path,
                "raw_arrival_response": raw_arrival_response,
                "selected_arrivals": [],
            }

    realtime_arrivals = raw_arrival_response.get("realtimeArrivalList", [])
    normalized_arrivals = [
        normalize_realtime_arrival_item(
            item,
            fallback_line=first_line,
            line_name_map=subway_id_line_map,
        )
        for item in realtime_arrivals
        if isinstance(item, dict)
    ]

    direction_filtered_arrivals = filter_arrivals_for_first_segment(
        normalized_arrivals,
        subway_id=station_info["subway_id"],
        line=first_line,
        direction=first_direction,
    )
    line_filtered_arrivals = filter_arrivals_for_first_segment(
        normalized_arrivals,
        subway_id=station_info["subway_id"],
        line=first_line,
        direction=None,
    )
    filtered_arrivals = direction_filtered_arrivals or line_filtered_arrivals
    selected_arrivals = select_fastest_arrivals(filtered_arrivals, limit=top_n)

    return {
        "ok": True,
        "message": "success",
        "departure_station": station_info,
        "shortest_path": shortest_path,
        "first_segment": first_segment,
        "raw_arrival_response": raw_arrival_response,
        "all_arrivals": normalized_arrivals,
        "filtered_arrivals": filtered_arrivals,
        "filter_applied": "line+direction" if direction_filtered_arrivals else "line",
        "selected_arrivals": selected_arrivals,
    }


if __name__ == "__main__":
    result = get_realtime_arrivals_for_shortest_path(
        start_station_name="강남",
        end_station_name="홍대입구",
        start_line="2호선",
        end_line="2호선",
        route_type="min_time",
        search_dt="2026-05-22 12:30:30",
        top_n=2,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
