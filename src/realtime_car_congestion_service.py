"""SK 실시간 칸별 혼잡도 API와 CSV 폴백을 함께 다루는 서비스 모듈."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from src.api_shortest_path import fetch_shortest_path_by_name, load_env_file, load_station_master
from src.congestion_lookup import get_congestion_by_station_key, load_congestion_data


BASE_DIR = Path.cwd()
CACHE_DIR = BASE_DIR / "data" / "cache"
USAGE_STATE_PATH = CACHE_DIR / "sk_realtime_congestion_usage.json"
NO_PROXY_OPENER = build_opener(ProxyHandler({}))

# The free tier is small, so default to a strict local guard even before
# the remote provider rejects additional calls.
DEFAULT_MONTHLY_LIMIT = 10


# 실시간 혼잡도 API 엔드포인트, 키, 월 한도 설정을 읽어온다.
def _load_live_api_settings() -> dict[str, Any]:
    load_env_file()

    endpoint = (
        os.getenv("SK_SUBWAY_CONGESTION_URL")
        or os.getenv("SK_REALTIME_CONGESTION_URL")
        or ""
    ).strip()
    api_key = (
        os.getenv("SK_APP_KEY")
        or os.getenv("SK_OPENAPI_KEY")
        or os.getenv("SK_API_KEY")
        or ""
    ).strip()
    monthly_limit = int(
        (os.getenv("SK_REALTIME_CONGESTION_MONTHLY_LIMIT") or DEFAULT_MONTHLY_LIMIT)
    )

    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "monthly_limit": monthly_limit,
        "timeout_seconds": int(os.getenv("SK_REALTIME_CONGESTION_TIMEOUT", "10")),
    }


# 사용량 집계를 위한 현재 연월 키를 만든다.
def _current_month(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


# 월별 사용량 캐시의 기본 상태를 만든다.
def _default_usage_state(now: datetime | None = None) -> dict[str, Any]:
    return {
        "month": _current_month(now),
        "used_calls": 0,
        "limit_reached": False,
        "limit_reached_reason": "",
        "last_call_at": "",
        "last_error": "",
    }


# 로컬 캐시에서 월별 실시간 API 사용량 상태를 읽어온다.
def load_usage_state(now: datetime | None = None) -> dict[str, Any]:
    if not USAGE_STATE_PATH.exists():
        return _default_usage_state(now)

    try:
        state = json.loads(USAGE_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_usage_state(now)

    if state.get("month") != _current_month(now):
        return _default_usage_state(now)

    return {
        "month": str(state.get("month", _current_month(now))),
        "used_calls": int(state.get("used_calls", 0)),
        "limit_reached": bool(state.get("limit_reached", False)),
        "limit_reached_reason": str(state.get("limit_reached_reason", "")),
        "last_call_at": str(state.get("last_call_at", "")),
        "last_error": str(state.get("last_error", "")),
    }


# 월별 실시간 API 사용량 상태를 로컬 파일로 저장한다.
def save_usage_state(state: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    USAGE_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 실시간 API 호출 전 로컬 사용량 카운터를 선반영한다.
def _reserve_live_call(now: datetime | None = None) -> dict[str, Any]:
    state = load_usage_state(now)
    state["used_calls"] += 1
    state["last_call_at"] = (now or datetime.now()).isoformat(timespec="seconds")
    save_usage_state(state)
    return state


# 원격 쿼터 초과를 감지했을 때 상태 파일에 기록한다.
def _mark_limit_reached(reason: str, now: datetime | None = None) -> dict[str, Any]:
    state = load_usage_state(now)
    state["limit_reached"] = True
    state["limit_reached_reason"] = reason
    state["last_error"] = reason
    save_usage_state(state)
    return state


# 마지막 오류 메시지를 상태 파일에 저장한다.
def _mark_last_error(error_message: str, now: datetime | None = None) -> dict[str, Any]:
    state = load_usage_state(now)
    state["last_error"] = error_message
    save_usage_state(state)
    return state


# 설정 누락이나 월 한도 초과 여부를 먼저 확인한다.
def _can_use_live_api(settings: dict[str, Any], now: datetime | None = None) -> tuple[bool, str]:
    if not settings["endpoint"] or not settings["api_key"]:
        return False, "live_api_not_configured"

    state = load_usage_state(now)
    if state["limit_reached"]:
        return False, "remote_quota_exceeded"
    if state["used_calls"] >= settings["monthly_limit"]:
        return False, "local_monthly_quota_guard"
    return True, ""


# CSV 폴백 조회에 필요한 요일 타입을 계산한다.
def _day_type_from_datetime(target_dt: datetime) -> str:
    weekday = target_dt.weekday()
    if weekday == 5:
        return "토요일"
    if weekday == 6:
        return "일요일"
    return "평일"


# CSV 폴백 조회에 필요한 시각 문자열을 만든다.
def _time_text_from_datetime(target_dt: datetime) -> str:
    return target_dt.strftime("%H:%M")


# 역명과 호선으로 실시간/CSV 조회 공통 역 컨텍스트를 찾는다.
def resolve_station_context(station_name: str, line: str) -> dict[str, str]:
    rows = load_station_master()
    normalized_station_name = station_name.strip()
    normalized_line = line.strip()

    matches = [
        row for row in rows
        if row.get("station_name_norm", "").strip() == normalized_station_name
        and row.get("line", "").strip() == normalized_line
    ]

    if not matches:
        raise ValueError(f"Station not found: {line} {station_name}")

    row = matches[0]
    return {
        "line": row.get("line", "").strip(),
        "station_name": row.get("station_name", "").strip(),
        "station_name_norm": row.get("station_name_norm", "").strip(),
        "station_key": row.get("station_key", "").strip(),
        "station_id": row.get("station_id", "").strip(),
        "subway_id": row.get("subway_id", "").strip(),
        "api_station_name": row.get("api_station_name", "").strip(),
    }


# 실시간 API를 쓰지 못할 때 CSV 기반 혼잡도 결과를 반환한다.
def get_csv_fallback_congestion(
    *,
    station_name: str,
    line: str,
    direction: str,
    target_dt: datetime | None = None,
    fallback_reason: str = "",
) -> dict[str, Any]:
    target_dt = target_dt or datetime.now()
    station_context = resolve_station_context(station_name, line)
    congestion_df = load_congestion_data()
    day_type = _day_type_from_datetime(target_dt)
    time_text = _time_text_from_datetime(target_dt)
    csv_result = get_congestion_by_station_key(
        df=congestion_df,
        day_type=day_type,
        line=line,
        station_key=station_context["station_key"],
        direction=direction,
        time_text=time_text,
    )

    return {
        "ok": csv_result is not None,
        "source": "csv_fallback",
        "fallback_reason": fallback_reason,
        "requested_at": target_dt.isoformat(timespec="seconds"),
        "station": station_context,
        "day_type": day_type,
        "time_text": time_text,
        "direction": direction,
        "live": None,
        "csv": csv_result,
    }


# 템플릿 형태의 SK API 엔드포인트를 실제 요청 URL로 치환한다.
def _build_live_request_url(
    endpoint: str,
    *,
    station_context: dict[str, str],
    target_dt: datetime,
    direction: str,
) -> str:
    # Keep the endpoint fully configurable because the app will later use the
    # exact SK Open API URL pattern that the team finalizes.
    replacements = {
        "{station_name}": quote(station_context["station_name"], safe=""),
        "{station_name_norm}": quote(station_context["station_name_norm"], safe=""),
        "{api_station_name}": quote(station_context["api_station_name"], safe=""),
        "{station_id}": quote(station_context["station_id"], safe=""),
        "{subway_id}": quote(station_context["subway_id"], safe=""),
        "{line}": quote(station_context["line"], safe=""),
        "{direction}": quote(direction, safe=""),
        "{date}": quote(target_dt.strftime("%Y-%m-%d"), safe=""),
        "{datetime}": quote(target_dt.strftime("%Y-%m-%d %H:%M:%S"), safe=""),
    }

    request_url = endpoint
    for placeholder, value in replacements.items():
        request_url = request_url.replace(placeholder, value)

    return request_url


# 다양한 응답 포맷에서 칸별 혼잡도 리스트만 추출한다.
def _extract_live_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("cars", "carCongestionList", "contents", "data", "result", "body"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested_items = _extract_live_items(value)
            if nested_items:
                return nested_items

    return []


# 여러 후보 키 중 처음 존재하는 값을 꺼낸다.
def _pick_first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


# 칸별 혼잡도 원본 항목을 공통 응답 형식으로 정규화한다.
def _normalize_live_car_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "car_no": _pick_first_present(item, ["carNo", "carNumber", "carIdx", "car"]),
        "congestion": _pick_first_present(
            item,
            ["congestion", "congestionScore", "congestionValue", "score", "rate"],
        ),
        "congestion_level": _pick_first_present(
            item,
            ["congestionLevel", "level", "status", "grade"],
        ),
        "description": _pick_first_present(item, ["description", "message", "text"]),
        "raw": item,
    }


# 응답 내용이나 상태 코드로 쿼터 초과 여부를 판정한다.
def _is_quota_exceeded(payload: Any, status_code: int | None, error_text: str = "") -> bool:
    candidates: list[str] = []
    if isinstance(payload, dict):
        for key in ("message", "msg", "error", "description", "resultMessage"):
            value = payload.get(key)
            if isinstance(value, str):
                candidates.append(value.lower())

        header = payload.get("header")
        if isinstance(header, dict):
            for key in ("resultMsg", "resultMessage"):
                value = header.get(key)
                if isinstance(value, str):
                    candidates.append(value.lower())

    if error_text:
        candidates.append(error_text.lower())
    if status_code == 429:
        return True

    keywords = ("quota", "limit", "too many", "exceed", "usage", "호출", "초과", "한도")
    return any(keyword in text for text in candidates for keyword in keywords)


# SK 실시간 칸별 혼잡도 API를 호출한다.
def fetch_live_car_congestion(
    *,
    station_name: str,
    line: str,
    direction: str,
    target_dt: datetime | None = None,
) -> dict[str, Any]:
    settings = _load_live_api_settings()
    target_dt = target_dt or datetime.now()
    can_call, blocked_reason = _can_use_live_api(settings, target_dt)
    if not can_call:
        return {
            "ok": False,
            "source": "sk_live",
            "error": blocked_reason,
            "cars": [],
            "request_url": None,
        }

    station_context = resolve_station_context(station_name, line)
    request_url = _build_live_request_url(
        settings["endpoint"],
        station_context=station_context,
        target_dt=target_dt,
        direction=direction,
    )

    # Reserve the call before the request so the local counter is conservative.
    _reserve_live_call(target_dt)

    request = Request(
        request_url,
        headers={
            "accept": "application/json",
            "appKey": settings["api_key"],
        },
    )

    try:
        with NO_PROXY_OPENER.open(request, timeout=settings["timeout_seconds"]) as response:
            status_code = getattr(response, "status", 200)
            body_text = response.read().decode("utf-8", errors="replace")

        payload = json.loads(body_text)
        if _is_quota_exceeded(payload, status_code):
            _mark_limit_reached("remote_quota_exceeded", target_dt)
            return {
                "ok": False,
                "source": "sk_live",
                "error": "remote_quota_exceeded",
                "cars": [],
                "request_url": request_url,
                "raw": payload,
            }

        raw_items = _extract_live_items(payload)
        cars = [_normalize_live_car_item(item) for item in raw_items]
        cars = [car for car in cars if any(car[key] not in (None, "") for key in ("car_no", "congestion", "congestion_level"))]

        if not cars:
            _mark_last_error("live_response_unparseable", target_dt)
            return {
                "ok": False,
                "source": "sk_live",
                "error": "live_response_unparseable",
                "cars": [],
                "request_url": request_url,
                "raw": payload,
            }

        return {
            "ok": True,
            "source": "sk_live",
            "error": "",
            "request_url": request_url,
            "requested_at": target_dt.isoformat(timespec="seconds"),
            "station": station_context,
            "direction": direction,
            "cars": cars,
            "raw": payload,
        }

    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        payload: Any
        try:
            payload = json.loads(error_text)
        except ValueError:
            payload = {"text": error_text}

        if _is_quota_exceeded(payload, exc.code, error_text):
            _mark_limit_reached("remote_quota_exceeded", target_dt)
            return {
                "ok": False,
                "source": "sk_live",
                "error": "remote_quota_exceeded",
                "cars": [],
                "request_url": request_url,
                "raw": payload,
            }

        _mark_last_error(f"http_error_{exc.code}", target_dt)
        return {
            "ok": False,
            "source": "sk_live",
            "error": f"http_error_{exc.code}",
            "cars": [],
            "request_url": request_url,
            "raw": payload,
        }

    except (URLError, TimeoutError, ValueError) as exc:
        _mark_last_error(str(exc), target_dt)
        return {
            "ok": False,
            "source": "sk_live",
            "error": str(exc),
            "cars": [],
            "request_url": request_url,
        }


# 실시간 호출 실패 시 자동으로 CSV 혼잡도 폴백을 적용한다.
def get_car_congestion_with_fallback(
    *,
    station_name: str,
    line: str,
    direction: str,
    target_dt: datetime | None = None,
) -> dict[str, Any]:
    target_dt = target_dt or datetime.now()
    live_result = fetch_live_car_congestion(
        station_name=station_name,
        line=line,
        direction=direction,
        target_dt=target_dt,
    )

    if live_result.get("ok"):
        return {
            "ok": True,
            "source": "sk_live",
            "fallback_used": False,
            "fallback_reason": "",
            "requested_at": target_dt.isoformat(timespec="seconds"),
            "station": live_result.get("station"),
            "direction": direction,
            "live": live_result,
            "csv": None,
        }

    csv_fallback = get_csv_fallback_congestion(
        station_name=station_name,
        line=line,
        direction=direction,
        target_dt=target_dt,
        fallback_reason=str(live_result.get("error", "")),
    )

    return {
        "ok": csv_fallback.get("ok", False),
        "source": csv_fallback["source"],
        "fallback_used": True,
        "fallback_reason": csv_fallback["fallback_reason"],
        "requested_at": target_dt.isoformat(timespec="seconds"),
        "station": csv_fallback["station"],
        "direction": direction,
        "live": live_result,
        "csv": csv_fallback["csv"],
    }


# 최단경로의 첫 구간 기준으로 실시간 또는 CSV 혼잡도를 조회한다.
def get_first_segment_congestion_for_shortest_path(
    *,
    start_station_name: str,
    end_station_name: str,
    route_type: str = "min_time",
    start_line: str | None = None,
    end_line: str | None = None,
    search_dt: str | None = None,
) -> dict[str, Any]:
    path_result = fetch_shortest_path_by_name(
        start_station_name=start_station_name,
        end_station_name=end_station_name,
        route_type=route_type,
        start_line=start_line,
        end_line=end_line,
        search_dt=search_dt,
    )

    if not path_result.get("ok"):
        return {
            "ok": False,
            "message": "shortest_path_failed",
            "error": path_result.get("error"),
            "shortest_path": path_result.get("normalized_response"),
            "congestion": None,
        }

    shortest_path = path_result.get("normalized_response") or {}
    segments = shortest_path.get("segments") or []
    if not segments:
        return {
            "ok": False,
            "message": "shortest_path_has_no_segments",
            "error": "No route segments found.",
            "shortest_path": shortest_path,
            "congestion": None,
        }

    first_segment = segments[0]
    first_line = str(first_segment.get("line") or "").strip()
    first_station = str(first_segment.get("from_station") or start_station_name).strip()
    first_direction = str(first_segment.get("direction") or "").strip()

    target_dt = (
        datetime.strptime(search_dt, "%Y-%m-%d %H:%M:%S")
        if search_dt
        else datetime.now()
    )

    congestion_result = get_car_congestion_with_fallback(
        station_name=first_station,
        line=first_line,
        direction=first_direction,
        target_dt=target_dt,
    )

    return {
        "ok": congestion_result.get("ok", False),
        "message": "success" if congestion_result.get("ok") else "congestion_lookup_failed",
        "shortest_path": shortest_path,
        "first_segment": first_segment,
        "congestion": congestion_result,
    }


if __name__ == "__main__":
    example = get_first_segment_congestion_for_shortest_path(
        start_station_name="강남",
        end_station_name="역삼",
        route_type="min_time",
        start_line="2호선",
        end_line="2호선",
        search_dt="2026-07-01 08:30:00",
    )
    print(json.dumps(example, ensure_ascii=False, indent=2))
