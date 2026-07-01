"""경로 타임라인 생성, 혼잡도 요약, 추천 점수 계산을 담당하는 모듈."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.api_shortest_path import fetch_shortest_path_by_name
from src.congestion_matcher import match_route_timeline_congestion
from src.realtime_arrival_api import get_realtime_arrivals_for_shortest_path


# 공통 숫자 파싱 보조 함수.
def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# datetime을 혼잡도 데이터의 day_type 형식으로 변환한다.
def get_day_type(target_dt: datetime) -> str:
    """현재 날짜를 혼잡도 CSV의 day_type 형식으로 변환한다."""
    weekday = target_dt.weekday()
    if weekday == 5:
        return "토요일"
    if weekday == 6:
        return "일요일"
    return "평일"


# 시간을 직전 30분 슬롯으로 내린다.
def floor_to_30min_slot(target_dt: datetime) -> datetime:
    """
    혼잡도 CSV 조회용으로 시각을 가장 가까운 이전 30분 슬롯으로 내린다.

    예:
    08:42:10 -> 08:30:00
    18:10:59 -> 18:00:00
    """
    floored_minute = 30 if target_dt.minute >= 30 else 0
    return target_dt.replace(minute=floored_minute, second=0, microsecond=0)


# 시간을 가장 가까운 30분 슬롯으로 반올림한다.
def round_to_30min_slot(target_dt: datetime) -> datetime:
    """
    화면 표시용으로 시각을 가장 가까운 30분 슬롯으로 반올림한다.

    기준:
    00~14분 -> 정시
    15~44분 -> 30분
    45~59분 -> 다음 정시
    """
    minute = target_dt.minute
    base = target_dt.replace(second=0, microsecond=0)

    if minute < 15:
        return base.replace(minute=0)
    if minute < 45:
        return base.replace(minute=30)
    return (base + timedelta(hours=1)).replace(minute=0)


# 슬롯 datetime을 CSV 키 형식의 문자열로 변환한다.
def datetime_to_time_slot_text(target_dt: datetime) -> str:
    return f"{target_dt.hour}시{target_dt.minute:02d}분"


# 슬롯 datetime을 비교용 분 단위 인덱스로 변환한다.
def datetime_to_time_index(target_dt: datetime) -> int:
    """기존 혼잡도 데이터와 맞추기 위해 새벽 0~4시는 다음 날 운행 시간대로 간주한다."""
    service_hour = target_dt.hour + 24 if target_dt.hour < 5 else target_dt.hour
    return service_hour * 60 + target_dt.minute


# 현재 시각과 열차 도착 ETA를 더해 예상 탑승 시각을 계산한다.
def estimate_boarding_time(
    current_dt: datetime,
    arrival_eta_seconds: int | None,
) -> datetime:
    """
    현재 시각 + 다음 열차 도착 예정 초 = 실제 탑승 예상 시각.

    도착 예정 초가 없으면 보수적으로 현재 시각을 그대로 사용한다.
    """
    eta_seconds = max(arrival_eta_seconds or 0, 0)
    return current_dt + timedelta(seconds=eta_seconds)


# 최단경로 API의 구간 시간을 초 단위 정수로 정규화한다.
def normalize_segment_duration_seconds(segment: dict[str, Any]) -> dict[str, int]:
    """최단경로 API의 reqHr / wtngHr를 초 단위 정수로 정규화한다."""
    travel_seconds = _safe_int(segment.get("travel_time"))
    waiting_seconds = _safe_int(segment.get("waiting_time"))
    return {
        "travel_seconds": travel_seconds,
        "waiting_seconds": waiting_seconds,
        "segment_total_seconds": travel_seconds + waiting_seconds,
    }


# HH:MM:SS 문자열을 기준 날짜의 datetime으로 파싱한다.
def _parse_clock_text_on_date(clock_text: str | None, base_dt: datetime) -> datetime | None:
    if not clock_text:
        return None

    try:
        hour, minute, second = map(int, str(clock_text).strip().split(":"))
    except ValueError:
        return None

    candidate = base_dt.replace(hour=hour, minute=minute, second=second, microsecond=0)

    # 새벽 시간인데 기준 시각보다 앞서면 다음 날 운행으로 본다.
    if candidate < base_dt and hour < 5:
        candidate += timedelta(days=1)

    return candidate


# 실시간 도착 API가 실패했을 때 첫 구간 예정 출발 시각으로 ETA를 추정한다.
def infer_arrival_eta_from_shortest_path(
    *,
    shortest_path: dict[str, Any],
    current_dt: datetime,
) -> tuple[int, str]:
    """
    실시간 도착 API가 실패하면 최단경로 첫 구간의 예정 출발 시각으로 ETA를 추정한다.

    우선순위:
    1. 첫 구간 train_departure_time - current_dt
    2. 예정 출발 시각이 없으면 0초
    """
    segments = shortest_path.get("segments") or []
    if not segments:
        return 0, "no_segments"

    first_segment = segments[0]
    scheduled_departure = _parse_clock_text_on_date(
        first_segment.get("train_departure_time"),
        current_dt,
    )
    if scheduled_departure is None:
        return 0, "missing_train_departure_time"

    eta_seconds = max(int((scheduled_departure - current_dt).total_seconds()), 0)
    return eta_seconds, "shortest_path_schedule"


# 실제 탑승 시각부터 구간별 예상 통과 시각과 30분 슬롯 타임라인을 만든다.
def build_route_timeline(
    *,
    current_dt: datetime,
    shortest_path: dict[str, Any],
    arrival_eta_seconds: int | None,
    slot_mode: str = "floor",
) -> dict[str, Any]:
    """
    1. 현재 시각에 첫 열차 ETA를 더해 탑승 시각 계산
    2. 각 구간의 이동시간/대기시간을 누적
    3. 역/구간별 예상 통과 시각 계산
    4. 통과 시각을 30분 단위 슬롯으로 변환
    5. 날짜 기준 day_type 계산
    """
    segments = shortest_path.get("segments") or []
    if not segments:
        return {
            "ok": False,
            "error": "No route segments found.",
            "boarding_time": None,
            "timeline": [],
        }

    if slot_mode not in {"floor", "round"}:
        raise ValueError("slot_mode must be 'floor' or 'round'.")

    slot_converter = floor_to_30min_slot if slot_mode == "floor" else round_to_30min_slot
    boarding_time = estimate_boarding_time(current_dt, arrival_eta_seconds)
    boarding_slot_dt = slot_converter(boarding_time)

    timeline: list[dict[str, Any]] = []
    cumulative_seconds = 0

    for index, segment in enumerate(segments, start=1):
        duration_info = normalize_segment_duration_seconds(segment)
        segment_start_dt = boarding_time + timedelta(seconds=cumulative_seconds)
        segment_end_dt = segment_start_dt + timedelta(
            seconds=duration_info["segment_total_seconds"]
        )
        slot_dt = slot_converter(segment_end_dt)

        timeline.append(
            {
                "segment_index": index,
                "from_station": segment.get("from_station"),
                "to_station": segment.get("to_station"),
                "line": segment.get("line"),
                "direction": segment.get("direction"),
                "train_no": segment.get("train_no"),
                "travel_seconds": duration_info["travel_seconds"],
                "waiting_seconds": duration_info["waiting_seconds"],
                "segment_total_seconds": duration_info["segment_total_seconds"],
                "cumulative_seconds": cumulative_seconds + duration_info["segment_total_seconds"],
                "expected_departure_time": segment_start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "expected_arrival_time": segment_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "day_type": get_day_type(segment_end_dt),
                "slot_mode": slot_mode,
                "time_slot": datetime_to_time_slot_text(slot_dt),
                "time_index": datetime_to_time_index(slot_dt),
                "slot_datetime": slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

        cumulative_seconds += duration_info["segment_total_seconds"]

    return {
        "ok": True,
        "current_time": current_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "arrival_eta_seconds": max(arrival_eta_seconds or 0, 0),
        "boarding_time": boarding_time.strftime("%Y-%m-%d %H:%M:%S"),
        "boarding_day_type": get_day_type(boarding_time),
        "boarding_time_slot": datetime_to_time_slot_text(boarding_slot_dt),
        "boarding_time_index": datetime_to_time_index(boarding_slot_dt),
        "slot_mode": slot_mode,
        "total_travel_seconds": cumulative_seconds,
        "timeline": timeline,
    }


# 실시간 도착정보 없이 최단경로 결과만으로 타임라인을 생성한다.
def _build_timeline_from_shortest_path_only(
    *,
    start_station_name: str,
    end_station_name: str,
    start_line: str | None,
    end_line: str | None,
    route_type: str,
    search_dt: str | None,
    slot_mode: str,
    fallback_reason: str,
) -> dict[str, Any]:
    current_dt = (
        datetime.strptime(search_dt, "%Y-%m-%d %H:%M:%S")
        if search_dt
        else datetime.now()
    )

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
            "timeline_result": None,
            "fallback_used": True,
            "fallback_reason": fallback_reason,
        }

    shortest_path = path_result.get("normalized_response") or {}
    arrival_eta_seconds, arrival_source = infer_arrival_eta_from_shortest_path(
        shortest_path=shortest_path,
        current_dt=current_dt,
    )
    timeline_result = build_route_timeline(
        current_dt=current_dt,
        shortest_path=shortest_path,
        arrival_eta_seconds=arrival_eta_seconds,
        slot_mode=slot_mode,
    )

    return {
        "ok": timeline_result.get("ok", False),
        "message": "success" if timeline_result.get("ok") else "timeline_build_failed",
        "search_dt": current_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "departure_station": None,
        "first_segment": (shortest_path.get("segments") or [None])[0],
        "selected_arrival": {
            "arrival_eta_seconds": arrival_eta_seconds,
            "source": arrival_source,
        },
        "shortest_path": shortest_path,
        "timeline_result": timeline_result,
        "fallback_used": True,
        "fallback_reason": fallback_reason,
    }


# 실시간 도착정보를 우선 사용하고 실패 시 최단경로 정보로 대체한다.
def build_route_timeline_from_api(
    *,
    start_station_name: str,
    end_station_name: str,
    start_line: str | None = None,
    end_line: str | None = None,
    route_type: str = "min_time",
    search_dt: str | None = None,
    slot_mode: str = "floor",
) -> dict[str, Any]:
    """
    실시간 도착 API를 우선 사용하고, 실패하면 최단경로 API 스케줄 정보로 폴백한다.
    """
    realtime_result = get_realtime_arrivals_for_shortest_path(
        start_station_name=start_station_name,
        end_station_name=end_station_name,
        start_line=start_line,
        end_line=end_line,
        route_type=route_type,
        search_dt=search_dt,
        top_n=1,
    )

    if not realtime_result.get("ok"):
        return _build_timeline_from_shortest_path_only(
            start_station_name=start_station_name,
            end_station_name=end_station_name,
            start_line=start_line,
            end_line=end_line,
            route_type=route_type,
            search_dt=search_dt,
            slot_mode=slot_mode,
            fallback_reason=str(realtime_result.get("error") or "realtime_arrival_failed"),
        )

    shortest_path = realtime_result.get("shortest_path") or {}
    selected_arrivals = realtime_result.get("selected_arrivals") or []
    if not selected_arrivals:
        return _build_timeline_from_shortest_path_only(
            start_station_name=start_station_name,
            end_station_name=end_station_name,
            start_line=start_line,
            end_line=end_line,
            route_type=route_type,
            search_dt=search_dt,
            slot_mode=slot_mode,
            fallback_reason="no_realtime_arrival_candidates",
        )

    first_arrival = selected_arrivals[0]
    current_dt = (
        datetime.strptime(search_dt, "%Y-%m-%d %H:%M:%S")
        if search_dt
        else datetime.now()
    )
    timeline_result = build_route_timeline(
        current_dt=current_dt,
        shortest_path=shortest_path,
        arrival_eta_seconds=_safe_int(first_arrival.get("arrival_eta_seconds")),
        slot_mode=slot_mode,
    )

    return {
        "ok": timeline_result.get("ok", False),
        "message": "success" if timeline_result.get("ok") else "timeline_build_failed",
        "search_dt": current_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "departure_station": realtime_result.get("departure_station"),
        "first_segment": realtime_result.get("first_segment"),
        "selected_arrival": first_arrival,
        "shortest_path": shortest_path,
        "timeline_result": timeline_result,
        "fallback_used": False,
        "fallback_reason": "",
    }


# 이미 받아둔 최단경로 결과를 다시 API 호출 없이 타임라인으로 바꾼다.
def build_route_timeline_from_shortest_path_result(
    *,
    path_result: dict[str, Any],
    current_dt: datetime,
    arrival_eta_seconds: int | None,
    slot_mode: str = "floor",
) -> dict[str, Any]:
    """이미 받아둔 최단경로 결과가 있을 때 재호출 없이 시간표만 계산한다."""
    if not path_result.get("ok"):
        return {
            "ok": False,
            "error": path_result.get("error"),
            "timeline_result": None,
        }

    shortest_path = path_result.get("normalized_response") or {}
    timeline_result = build_route_timeline(
        current_dt=current_dt,
        shortest_path=shortest_path,
        arrival_eta_seconds=arrival_eta_seconds,
        slot_mode=slot_mode,
    )

    return {
        "ok": timeline_result.get("ok", False),
        "shortest_path": shortest_path,
        "timeline_result": timeline_result,
    }


# 타임라인 생성 직후 구간별 혼잡도 매칭까지 한번에 수행한다.
def build_route_timeline_with_congestion_from_api(
    *,
    start_station_name: str,
    end_station_name: str,
    start_line: str | None = None,
    end_line: str | None = None,
    route_type: str = "min_time",
    search_dt: str | None = None,
    slot_mode: str = "floor",
) -> dict[str, Any]:
    """경로 시간표 생성 후 바로 구간별 혼잡도 매칭까지 수행한다."""
    timeline_api_result = build_route_timeline_from_api(
        start_station_name=start_station_name,
        end_station_name=end_station_name,
        start_line=start_line,
        end_line=end_line,
        route_type=route_type,
        search_dt=search_dt,
        slot_mode=slot_mode,
    )

    if not timeline_api_result.get("ok"):
        return {
            "ok": False,
            "message": timeline_api_result.get("message"),
            "error": timeline_api_result.get("error"),
            "timeline_result": timeline_api_result.get("timeline_result"),
            "congestion_result": None,
            "fallback_used": timeline_api_result.get("fallback_used", False),
            "fallback_reason": timeline_api_result.get("fallback_reason", ""),
        }

    congestion_result = match_route_timeline_congestion(
        timeline_api_result["timeline_result"]
    )

    return {
        "ok": congestion_result.get("ok", False),
        "message": "success" if congestion_result.get("ok") else "congestion_match_failed",
        "search_dt": timeline_api_result.get("search_dt"),
        "departure_station": timeline_api_result.get("departure_station"),
        "first_segment": timeline_api_result.get("first_segment"),
        "selected_arrival": timeline_api_result.get("selected_arrival"),
        "shortest_path": timeline_api_result.get("shortest_path"),
        "timeline_result": timeline_api_result.get("timeline_result"),
        "congestion_result": congestion_result,
        "fallback_used": timeline_api_result.get("fallback_used", False),
        "fallback_reason": timeline_api_result.get("fallback_reason", ""),
    }


# 동일 경로 중복 제거를 위한 구간 시그니처를 만든다.
def build_route_signature(shortest_path: dict[str, Any]) -> tuple:
    """
    같은 경로가 여러 route_type에서 중복으로 나올 수 있어서 구간 시퀀스로 서명을 만든다.
    """
    signature_items: list[tuple[str, str, str, str]] = []
    for segment in shortest_path.get("segments") or []:
        signature_items.append(
            (
                str(segment.get("from_station") or "").strip(),
                str(segment.get("to_station") or "").strip(),
                str(segment.get("line") or "").strip(),
                str(segment.get("direction") or "").strip(),
            )
        )
    return tuple(signature_items)


# 공통 실수 파싱 보조 함수.
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# 추천 점수 계산에 필요한 시간, 환승, 혼잡도 지표를 요약한다.
def summarize_route_metrics(route_result: dict[str, Any]) -> dict[str, Any]:
    """
    추천 점수 계산에 필요한 핵심 지표만 추린다.
    """
    shortest_path = route_result.get("shortest_path") or {}
    congestion_result = route_result.get("congestion_result") or {}
    congestion_summary = congestion_result.get("route_congestion_summary") or {}

    total_travel_seconds = _safe_int(
        (route_result.get("timeline_result") or {}).get("total_travel_seconds")
    )
    transfer_count = _safe_int(shortest_path.get("transfer_count"))
    average_congestion = congestion_summary.get("average_congestion")
    weighted_average_congestion = congestion_summary.get("weighted_average_congestion")
    weighted_average_congestion_level = congestion_summary.get("weighted_average_congestion_level")
    max_congestion = congestion_summary.get("max_congestion")
    max_congestion_level = congestion_summary.get("max_congestion_level")
    matched_segment_count = _safe_int(congestion_summary.get("matched_segment_count"))
    segment_count = len((route_result.get("timeline_result") or {}).get("timeline") or [])

    return {
        "total_travel_seconds": total_travel_seconds,
        "total_travel_minutes": round(total_travel_seconds / 60.0, 1),
        "transfer_count": transfer_count,
        "average_congestion": _safe_float(average_congestion) if average_congestion is not None else None,
        "weighted_average_congestion": _safe_float(weighted_average_congestion) if weighted_average_congestion is not None else None,
        "weighted_average_congestion_level": weighted_average_congestion_level,
        "max_congestion": _safe_float(max_congestion) if max_congestion is not None else None,
        "max_congestion_level": max_congestion_level,
        "matched_segment_count": matched_segment_count,
        "segment_count": segment_count,
        "fallback_used": bool(route_result.get("fallback_used", False)),
    }


# 소요시간, 환승, 혼잡도, 폴백 여부를 반영한 추천 비용과 점수를 계산한다.
def compute_route_recommendation_score(route_result: dict[str, Any]) -> dict[str, Any]:
    """
    혼잡도를 가장 크게 반영하고, 소요시간/환승/폴백 사용 여부를 보조 지표로 감점한다.

    점수 방향:
    - 높을수록 추천
    - 평균 혼잡도와 최대 혼잡도에 가장 큰 패널티
    - 시간이 조금 더 걸리더라도 덜 붐비면 상위로 올 수 있게 설계
    """
    metrics = summarize_route_metrics(route_result)

    weighted_average_congestion = (
        metrics["weighted_average_congestion"]
        if metrics["weighted_average_congestion"] is not None
        else 160.0
    )
    max_congestion = metrics["max_congestion"] if metrics["max_congestion"] is not None else 170.0
    total_travel_seconds = metrics["total_travel_seconds"]
    transfer_count = metrics["transfer_count"]
    segment_count = metrics["segment_count"]
    matched_segment_count = metrics["matched_segment_count"]
    fallback_used = metrics["fallback_used"]

    travel_time_cost = round(total_travel_seconds / 60.0, 1)
    transfer_penalty = transfer_count * 8.0
    congestion_penalty = round((weighted_average_congestion * 0.6) + (max_congestion * 0.4), 1)
    unmatched_penalty = max(segment_count - matched_segment_count, 0) * 6.0
    fallback_penalty = 4.0 if fallback_used else 0.0

    recommendation_cost = round(
        travel_time_cost + transfer_penalty + congestion_penalty + unmatched_penalty + fallback_penalty,
        1,
    )
    score = 300.0 - recommendation_cost
    score = round(max(score, 0.0), 1)

    return {
        "score": score,
        "recommendation_cost": recommendation_cost,
        "metrics": metrics,
        "penalties": {
            "travel_time_cost": travel_time_cost,
            "congestion_penalty": round(congestion_penalty, 1),
            "transfer_penalty": round(transfer_penalty, 1),
            "unmatched_penalty": round(unmatched_penalty, 1),
            "fallback_penalty": round(fallback_penalty, 1),
        },
    }


# 경로를 한 줄 라벨로 표현한다.
def _build_route_label(route_result: dict[str, Any]) -> str:
    shortest_path = route_result.get("shortest_path") or {}
    segments = shortest_path.get("segments") or []
    if not segments:
        return "empty-route"

    first_station = str(segments[0].get("from_station") or "").strip()
    last_station = str(segments[-1].get("to_station") or "").strip()
    transfer_count = _safe_int(shortest_path.get("transfer_count"))
    return f"{first_station} -> {last_station} / 환승 {transfer_count}회"


# 여러 경로 후보를 수집하고 덜 붐비는 순서로 정렬한다.
def rank_least_crowded_routes(
    *,
    start_station_name: str,
    end_station_name: str,
    start_line: str | None = None,
    end_line: str | None = None,
    route_types: tuple[str, ...] = ("min_time", "min_transfer"),
    search_dt: str | None = None,
    slot_mode: str = "floor",
) -> dict[str, Any]:
    """
    여러 route_type 후보를 수집한 뒤 혼잡도 중심 추천 점수를 붙여 정렬한다.
    """
    raw_candidates: list[dict[str, Any]] = []

    for route_type in route_types:
        try:
            route_result = build_route_timeline_with_congestion_from_api(
                start_station_name=start_station_name,
                end_station_name=end_station_name,
                start_line=start_line,
                end_line=end_line,
                route_type=route_type,
                search_dt=search_dt,
                slot_mode=slot_mode,
            )
        except Exception as exc:
            raw_candidates.append(
                {
                    "route_type": route_type,
                    "ok": False,
                    "message": "route_build_failed",
                    "error": str(exc),
                }
            )
            continue

        if not route_result.get("ok"):
            raw_candidates.append(
                {
                    "route_type": route_type,
                    "ok": False,
                    "message": route_result.get("message"),
                    "error": route_result.get("error"),
                }
            )
            continue

        score_result = compute_route_recommendation_score(route_result)
        raw_candidates.append(
            {
                "route_type": route_type,
                "ok": True,
                "label": _build_route_label(route_result),
                "signature": build_route_signature(route_result.get("shortest_path") or {}),
                "score": score_result["score"],
                "recommendation_cost": score_result["recommendation_cost"],
                "metrics": score_result["metrics"],
                "penalties": score_result["penalties"],
                "result": route_result,
            }
        )

    deduped_candidates: dict[tuple, dict[str, Any]] = {}
    failed_candidates: list[dict[str, Any]] = []

    for candidate in raw_candidates:
        if not candidate.get("ok"):
            failed_candidates.append(candidate)
            continue

        signature = candidate["signature"]
        if signature not in deduped_candidates:
            deduped_candidates[signature] = {
                **candidate,
                "route_types": [candidate["route_type"]],
            }
            continue

        deduped_candidates[signature]["route_types"].append(candidate["route_type"])
        if candidate["recommendation_cost"] < deduped_candidates[signature]["recommendation_cost"]:
            existing_route_types = deduped_candidates[signature]["route_types"]
            deduped_candidates[signature] = {
                **candidate,
                "route_types": existing_route_types,
            }

    ranked_routes = sorted(
        deduped_candidates.values(),
        key=lambda item: (
            item["recommendation_cost"],
            item["metrics"]["total_travel_seconds"],
            item["metrics"]["transfer_count"],
        ),
    )

    for rank, candidate in enumerate(ranked_routes, start=1):
        candidate["rank"] = rank

    return {
        "ok": len(ranked_routes) > 0,
        "start_station_name": start_station_name,
        "end_station_name": end_station_name,
        "search_dt": search_dt,
        "ranked_routes": ranked_routes,
        "failed_candidates": failed_candidates,
        "alternative_route": build_alternative_route_suggestion(ranked_routes),
    }


# 최단 경로보다 조금 느려도 혼잡도가 충분히 낮으면 대체 경로를 제안한다.
def build_alternative_route_suggestion(ranked_routes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    최단 경로보다 시간이 조금 늘어나도 혼잡도가 크게 낮으면 대체 경로로 제안한다.
    """
    if len(ranked_routes) < 2:
        return None

    min_time_route = next(
        (route for route in ranked_routes if "min_time" in route.get("route_types", [])),
        ranked_routes[0],
    )

    baseline_minutes = _safe_float(min_time_route["metrics"].get("total_travel_minutes"))
    baseline_weighted = _safe_float(min_time_route["metrics"].get("weighted_average_congestion"))
    baseline_max = _safe_float(min_time_route["metrics"].get("max_congestion"))

    for candidate in ranked_routes:
        if candidate is min_time_route:
            continue

        candidate_minutes = _safe_float(candidate["metrics"].get("total_travel_minutes"))
        candidate_weighted = _safe_float(candidate["metrics"].get("weighted_average_congestion"))
        candidate_max = _safe_float(candidate["metrics"].get("max_congestion"))

        extra_minutes = round(candidate_minutes - baseline_minutes, 1)
        weighted_drop = round(baseline_weighted - candidate_weighted, 1)
        max_drop = round(baseline_max - candidate_max, 1)

        if extra_minutes <= 8.0 and (weighted_drop >= 10.0 or max_drop >= 15.0):
            return {
                "baseline_label": min_time_route.get("label"),
                "alternative_label": candidate.get("label"),
                "extra_minutes": extra_minutes,
                "weighted_congestion_drop": weighted_drop,
                "max_congestion_drop": max_drop,
                "reason": "시간 증가는 작고 혼잡도 개선 폭은 큼",
                "baseline_route_types": min_time_route.get("route_types", []),
                "alternative_route_types": candidate.get("route_types", []),
            }

    return None


# 프론트에서 바로 쓰기 좋은 납작한 경로 DTO로 변환한다.
def flatten_ranked_route(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    프론트 카드 렌더링에 필요한 핵심 필드만 남긴 납작한 경로 DTO.
    """
    route_result = candidate.get("result") or {}
    shortest_path = route_result.get("shortest_path") or {}
    timeline_result = route_result.get("timeline_result") or {}
    congestion_result = route_result.get("congestion_result") or {}
    congestion_summary = congestion_result.get("route_congestion_summary") or {}
    segments = shortest_path.get("segments") or []
    first_segment = segments[0] if segments else {}
    last_segment = segments[-1] if segments else {}
    selected_arrival = route_result.get("selected_arrival") or {}

    return {
        "rank": candidate.get("rank"),
        "label": candidate.get("label"),
        "route_types": candidate.get("route_types", []),
        "score": candidate.get("score"),
        "recommendation_cost": candidate.get("recommendation_cost"),
        "start_station": first_segment.get("from_station"),
        "end_station": last_segment.get("to_station"),
        "line": first_segment.get("line"),
        "direction": first_segment.get("direction"),
        "segment_count": candidate.get("metrics", {}).get("segment_count"),
        "transfer_count": candidate.get("metrics", {}).get("transfer_count"),
        "total_travel_seconds": candidate.get("metrics", {}).get("total_travel_seconds"),
        "total_travel_minutes": candidate.get("metrics", {}).get("total_travel_minutes"),
        "arrival_eta_seconds": selected_arrival.get("arrival_eta_seconds"),
        "average_congestion": candidate.get("metrics", {}).get("average_congestion"),
        "weighted_average_congestion": candidate.get("metrics", {}).get("weighted_average_congestion"),
        "weighted_average_congestion_level": candidate.get("metrics", {}).get("weighted_average_congestion_level"),
        "max_congestion": candidate.get("metrics", {}).get("max_congestion"),
        "max_congestion_level": candidate.get("metrics", {}).get("max_congestion_level")
        or congestion_summary.get("max_congestion_level"),
        "matched_segment_count": candidate.get("metrics", {}).get("matched_segment_count"),
        "fallback_used": candidate.get("metrics", {}).get("fallback_used"),
        "fallback_reason": route_result.get("fallback_reason"),
        "boarding_time": timeline_result.get("boarding_time"),
        "boarding_day_type": timeline_result.get("boarding_day_type"),
        "boarding_time_slot": timeline_result.get("boarding_time_slot"),
        "penalties": candidate.get("penalties", {}),
        "congestion_match_types": [
            row.get("congestion_match_type")
            for row in (congestion_result.get("matched_timeline") or [])
        ],
        "path_stations": [
            row.get("from_station")
            for row in segments
        ] + ([last_segment.get("to_station")] if last_segment.get("to_station") else []),
    }


# 실패한 경로 후보의 핵심 에러 정보만 정리한다.
def flatten_failed_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_type": candidate.get("route_type"),
        "message": candidate.get("message"),
        "error": candidate.get("error"),
    }


# 랭킹 결과 전체를 프론트용 응답 구조로 변환한다.
def to_frontend_ranked_routes_response(rank_result: dict[str, Any]) -> dict[str, Any]:
    """
    프론트에서 바로 쓰기 좋은 응답 형태로 변환한다.
    """
    return {
        "ok": rank_result.get("ok", False),
        "start_station_name": rank_result.get("start_station_name"),
        "end_station_name": rank_result.get("end_station_name"),
        "search_dt": rank_result.get("search_dt"),
        "routes": [
            flatten_ranked_route(candidate)
            for candidate in rank_result.get("ranked_routes", [])
        ],
        "alternative_route": rank_result.get("alternative_route"),
        "failed_routes": [
            flatten_failed_candidate(candidate)
            for candidate in rank_result.get("failed_candidates", [])
        ],
    }


if __name__ == "__main__":
    result = build_route_timeline_with_congestion_from_api(
        start_station_name="강남",
        end_station_name="서울대입구",
        start_line="2호선",
        end_line="2호선",
        route_type="min_time",
        search_dt="2026-07-01 08:30:00",
        slot_mode="floor",
    )
    print(result)
