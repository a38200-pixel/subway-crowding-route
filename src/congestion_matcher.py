"""구간 타임라인과 혼잡도 CSV를 매칭하고 경로 혼잡도 요약을 계산하는 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.api_shortest_path import load_station_master


BASE_DIR = Path.cwd()
CONGESTION_PATH = BASE_DIR / "data" / "processed" / "congestion_long_with_station_key.csv"


# 전처리된 혼잡도 CSV를 로드하고 매칭에 필요한 컬럼 타입을 정리한다.
def load_congestion_data() -> pd.DataFrame:
    """
    혼잡도 CSV를 DataFrame으로 읽고, 매칭에 필요한 컬럼 타입을 정리한다.
    """
    if not CONGESTION_PATH.exists():
        raise FileNotFoundError(f"congestion data not found: {CONGESTION_PATH}")

    df = pd.read_csv(CONGESTION_PATH, encoding="utf-8-sig")
    df = df.fillna("")
    df["time_index"] = pd.to_numeric(df["time_index"], errors="coerce")
    df["congestion"] = pd.to_numeric(df["congestion"], errors="coerce")
    df["line"] = df["line"].astype(str).str.strip()
    df["station_name_norm"] = df["station_name_norm"].astype(str).str.strip()
    df["direction"] = df["direction"].astype(str).str.strip()
    df["time_slot"] = df["time_slot"].astype(str).str.strip()
    df["day_type"] = df["day_type"].astype(str).str.strip()
    return df


# station_master를 기준으로 `(line, station_name_norm)` 인덱스를 만든다.
def build_station_name_index() -> dict[tuple[str, str], dict[str, str]]:
    """
    station_master 기준으로 (line, station_name_norm) -> 대표 역 정보 매핑을 만든다.
    """
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in load_station_master():
        line = row.get("line", "").strip()
        station_name_norm = row.get("station_name_norm", "").strip()
        if not line or not station_name_norm:
            continue
        index[(line, station_name_norm)] = row
    return index


# 경로 API 방향 표기와 혼잡도 CSV 방향 표기의 차이를 보정할 후보 맵을 만든다.
def build_direction_mapper() -> dict[str, list[str]]:
    """
    API 방향 표기와 혼잡도 CSV 방향 표기가 다를 수 있어서 후보 방향 목록을 넓게 잡는다.
    """
    return {
        "상선": ["상선", "상행", "내선"],
        "하선": ["하선", "하행", "외선"],
        "상행": ["상행", "상선", "내선"],
        "하행": ["하행", "하선", "외선"],
        "내선": ["내선", "상선", "상행"],
        "외선": ["외선", "하선", "하행"],
        "": [],
    }


# 실제 데이터에 존재하는 방향만 남기도록 방향 후보를 정리한다.
def resolve_direction_candidates(
    *,
    line: str,
    raw_direction: str,
    congestion_df: pd.DataFrame,
    direction_mapper: dict[str, list[str]],
) -> list[str]:
    allowed = set(
        congestion_df.loc[congestion_df["line"] == line, "direction"]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )

    candidates: list[str] = []
    for candidate in [raw_direction, *direction_mapper.get(raw_direction, [])]:
        normalized = (candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    matched_candidates = [candidate for candidate in candidates if candidate in allowed]
    if matched_candidates:
        return matched_candidates
    return candidates or sorted(allowed)


# 구간에서 혼잡도 조회 기준이 되는 대표 역명을 구한다.
def _segment_station_name_norm(segment: dict[str, Any]) -> str:
    return (
        str(segment.get("station_name_norm") or "").strip()
        or str(segment.get("from_station") or "").strip()
    )


# 매칭된 혼잡도 행을 구간 응답 형식으로 합친다.
def _row_to_match_payload(
    *,
    segment: dict[str, Any],
    row: pd.Series,
    station_key: str,
    matched_direction: str,
    match_type: str,
    fallback_time_slot: str = "",
    fallback_time_index: int | None = None,
) -> dict[str, Any]:
    congestion_value = None if pd.isna(row.get("congestion")) else float(row["congestion"])
    payload = {
        **segment,
        "station_name_norm": _segment_station_name_norm(segment),
        "station_key": station_key,
        "matched_direction": matched_direction,
        "congestion": congestion_value,
        "congestion_level": classify_congestion_level(congestion_value),
        "congestion_match_type": match_type,
        "congestion_match_found": True,
    }

    if fallback_time_slot:
        payload["fallback_time_slot"] = fallback_time_slot
    if fallback_time_index is not None:
        payload["fallback_time_index"] = fallback_time_index
    return payload


# 수치형 혼잡도를 프론트용 5단계 레벨 문자열로 변환한다.
def classify_congestion_level(congestion_value: float | None) -> str | None:
    """
    혼잡도 수치를 프론트 표시용 5단계 등급으로 재분류한다.
    """
    if congestion_value is None:
        return None
    if congestion_value <= 20:
        return "여유"
    if congestion_value <= 40:
        return "보통"
    if congestion_value <= 70:
        return "주의"
    if congestion_value <= 90:
        return "혼잡"
    return "매우 혼잡"


# day_type, line, station, direction, time_slot 기준의 1차 정확 매칭을 수행한다.
def find_direct_match(
    *,
    congestion_df: pd.DataFrame,
    day_type: str,
    line: str,
    station_name_norm: str,
    direction: str,
    time_slot: str,
) -> pd.DataFrame:
    return congestion_df[
        (congestion_df["day_type"] == day_type)
        & (congestion_df["line"] == line)
        & (congestion_df["station_name_norm"] == station_name_norm)
        & (congestion_df["direction"] == direction)
        & (congestion_df["time_slot"] == time_slot)
    ]


# 같은 역과 방향에서 가장 가까운 시간대의 혼잡도 행을 찾는다.
def find_nearest_time_match(
    *,
    congestion_df: pd.DataFrame,
    day_type: str,
    line: str,
    station_name_norm: str,
    direction: str,
    target_time_index: int,
) -> pd.Series | None:
    candidates = congestion_df[
        (congestion_df["day_type"] == day_type)
        & (congestion_df["line"] == line)
        & (congestion_df["station_name_norm"] == station_name_norm)
        & (congestion_df["direction"] == direction)
    ].copy()

    if candidates.empty:
        return None

    candidates["time_distance"] = (candidates["time_index"] - target_time_index).abs()
    candidates = candidates.sort_values(["time_distance", "time_index"])
    return candidates.iloc[0]


# 같은 호선 평균값으로 최종 폴백할 때 사용할 대표 행을 만든다.
def build_line_average_fallback(
    *,
    congestion_df: pd.DataFrame,
    day_type: str,
    line: str,
    target_time_index: int,
) -> pd.Series | None:
    same_line_time = congestion_df[
        (congestion_df["day_type"] == day_type)
        & (congestion_df["line"] == line)
        & (congestion_df["time_index"] == target_time_index)
    ].copy()

    fallback_df = same_line_time if not same_line_time.empty else congestion_df[congestion_df["line"] == line].copy()
    fallback_df = fallback_df[pd.notna(fallback_df["congestion"])].copy()
    if fallback_df.empty:
        return None

    fallback_df["time_distance"] = (fallback_df["time_index"] - target_time_index).abs()
    exemplar = fallback_df.sort_values(["time_distance", "time_index"]).iloc[0].copy()
    exemplar["congestion"] = round(float(fallback_df["congestion"].mean()), 1)
    exemplar["station_name"] = ""
    exemplar["station_name_norm"] = ""
    exemplar["station_key"] = ""
    return exemplar


# 단일 구간에 대해 direct, direction mapping, fallback 순서로 혼잡도를 매칭한다.
def match_timeline_segment_congestion(
    *,
    segment: dict[str, Any],
    congestion_df: pd.DataFrame,
    station_name_index: dict[tuple[str, str], dict[str, str]],
    direction_mapper: dict[str, list[str]],
) -> dict[str, Any]:
    """
    1차: timeline + congestion_lookup 단순 연결
    2차: direction_mapper 적용
    3차: 가까운 시간대 -> 같은 호선 평균 fallback
    """
    line = str(segment.get("line") or "").strip()
    day_type = str(segment.get("day_type") or "").strip()
    station_name_norm = _segment_station_name_norm(segment)
    raw_direction = str(segment.get("direction") or "").strip()
    time_slot = str(segment.get("time_slot") or "").strip()
    time_index = int(segment.get("time_index") or 0)

    station_info = station_name_index.get((line, station_name_norm), {})
    station_key = station_info.get("station_key", "").strip()

    direct_match = find_direct_match(
        congestion_df=congestion_df,
        day_type=day_type,
        line=line,
        station_name_norm=station_name_norm,
        direction=raw_direction,
        time_slot=time_slot,
    )
    if not direct_match.empty:
        return _row_to_match_payload(
            segment=segment,
            row=direct_match.iloc[0],
            station_key=station_key,
            matched_direction=raw_direction,
            match_type="direct",
        )

    direction_candidates = resolve_direction_candidates(
        line=line,
        raw_direction=raw_direction,
        congestion_df=congestion_df,
        direction_mapper=direction_mapper,
    )

    for candidate_direction in direction_candidates:
        direction_match = find_direct_match(
            congestion_df=congestion_df,
            day_type=day_type,
            line=line,
            station_name_norm=station_name_norm,
            direction=candidate_direction,
            time_slot=time_slot,
        )
        if not direction_match.empty:
            return _row_to_match_payload(
                segment=segment,
                row=direction_match.iloc[0],
                station_key=station_key,
                matched_direction=candidate_direction,
                match_type="direction_mapped",
            )

    for candidate_direction in direction_candidates:
        nearest_time_match = find_nearest_time_match(
            congestion_df=congestion_df,
            day_type=day_type,
            line=line,
            station_name_norm=station_name_norm,
            direction=candidate_direction,
            target_time_index=time_index,
        )
        if nearest_time_match is not None:
            return _row_to_match_payload(
                segment=segment,
                row=nearest_time_match,
                station_key=station_key,
                matched_direction=candidate_direction,
                match_type="nearest_time_fallback",
                fallback_time_slot=str(nearest_time_match.get("time_slot", "")),
                fallback_time_index=int(nearest_time_match.get("time_index", 0)),
            )

    line_average_match = build_line_average_fallback(
        congestion_df=congestion_df,
        day_type=day_type,
        line=line,
        target_time_index=time_index,
    )
    if line_average_match is not None:
        return _row_to_match_payload(
            segment=segment,
            row=line_average_match,
            station_key=station_key,
            matched_direction=str(line_average_match.get("direction", "")),
            match_type="line_average_fallback",
            fallback_time_slot=str(line_average_match.get("time_slot", "")),
            fallback_time_index=int(line_average_match.get("time_index", 0)),
        )

    return {
        **segment,
        "station_name_norm": station_name_norm,
        "station_key": station_key,
        "matched_direction": raw_direction,
        "congestion": None,
        "congestion_level": None,
        "congestion_match_type": "unmatched",
        "congestion_match_found": False,
    }


# 매칭된 구간들을 기준으로 평균, 가중평균, 최대 혼잡도를 계산한다.
def summarize_route_congestion(matched_segments: list[dict[str, Any]]) -> dict[str, Any]:
    matched_df = pd.DataFrame(matched_segments)
    if matched_df.empty or "congestion" not in matched_df.columns:
        return {
            "matched_segment_count": 0,
            "average_congestion": None,
            "weighted_average_congestion": None,
            "weighted_average_congestion_level": None,
            "max_congestion": None,
            "max_congestion_segment_index": None,
            "max_congestion_level": None,
        }

    valid_df = matched_df[pd.notna(matched_df["congestion"])].copy()
    if valid_df.empty:
        return {
            "matched_segment_count": 0,
            "average_congestion": None,
            "weighted_average_congestion": None,
            "weighted_average_congestion_level": None,
            "max_congestion": None,
            "max_congestion_segment_index": None,
            "max_congestion_level": None,
        }

    valid_df["travel_seconds"] = pd.to_numeric(valid_df["travel_seconds"], errors="coerce").fillna(0)
    valid_df["weight_seconds"] = valid_df["travel_seconds"].where(valid_df["travel_seconds"] > 0, 1)
    weighted_average_congestion = float(
        (valid_df["congestion"] * valid_df["weight_seconds"]).sum() / valid_df["weight_seconds"].sum()
    )
    max_row = valid_df.loc[valid_df["congestion"].idxmax()]
    return {
        "matched_segment_count": int(len(valid_df)),
        "average_congestion": round(float(valid_df["congestion"].mean()), 1),
        "weighted_average_congestion": round(weighted_average_congestion, 1),
        "weighted_average_congestion_level": classify_congestion_level(weighted_average_congestion),
        "max_congestion": round(float(valid_df["congestion"].max()), 1),
        "max_congestion_segment_index": int(max_row["segment_index"]),
        "max_congestion_level": classify_congestion_level(float(max_row["congestion"])),
    }


# 타임라인 전체 구간에 혼잡도를 붙이고 경로 단위 요약을 반환한다.
def match_route_timeline_congestion(timeline_result: dict[str, Any]) -> dict[str, Any]:
    """
    1차: timeline + congestion_lookup 단순 연결
    2차: direction_mapper 추가
    3차: 매칭 실패 시 fallback 추가
    4차: 전체 경로 평균/최대 혼잡도 계산
    """
    if not timeline_result.get("ok"):
        return {
            "ok": False,
            "error": timeline_result.get("error"),
            "matched_timeline": [],
            "route_congestion_summary": None,
        }

    congestion_df = load_congestion_data()
    station_name_index = build_station_name_index()
    direction_mapper = build_direction_mapper()

    matched_timeline = [
        match_timeline_segment_congestion(
            segment=segment,
            congestion_df=congestion_df,
            station_name_index=station_name_index,
            direction_mapper=direction_mapper,
        )
        for segment in timeline_result.get("timeline", [])
    ]

    return {
        "ok": True,
        "current_time": timeline_result.get("current_time"),
        "boarding_time": timeline_result.get("boarding_time"),
        "slot_mode": timeline_result.get("slot_mode"),
        "matched_timeline": matched_timeline,
        "route_congestion_summary": summarize_route_congestion(matched_timeline),
    }
