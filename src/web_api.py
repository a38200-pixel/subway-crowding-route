from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.route_scorer import rank_least_crowded_routes, to_frontend_ranked_routes_response
from src.station_hotspots import DEFAULT_IMAGE_PATH, get_image_size, load_station_hotspots


BASE_DIR = Path(__file__).resolve().parents[1]
MIN_REGISTERED_HOTSPOT_WARNING_COUNT = 30

app = FastAPI(title="Subway Crowding Route API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StationSelection(BaseModel):
    station_key: str
    line: str
    station_name: str
    station_name_norm: str


class RecommendationRequest(BaseModel):
    departure_station: StationSelection
    arrival_station: StationSelection
    search_dt: str | None = None


def build_sample_route_payload(
    departure_station: StationSelection,
    arrival_station: StationSelection,
) -> dict[str, Any]:
    now = datetime.now().replace(second=0, microsecond=0)
    segment_rows = [
        {
            "segment_index": 1,
            "line": departure_station.line,
            "from_station": departure_station.station_name,
            "to_station": "중간 환승역",
            "expected_arrival_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "congestion": 54.0,
            "congestion_level": "보통",
            "congestion_match_type": "sample",
            "travel_seconds": 420,
        },
        {
            "segment_index": 2,
            "line": arrival_station.line,
            "from_station": "중간 환승역",
            "to_station": arrival_station.station_name,
            "expected_arrival_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "congestion": 71.0,
            "congestion_level": "다소혼잡",
            "congestion_match_type": "sample",
            "travel_seconds": 540,
        },
    ]
    return {
        "ok": True,
        "mode": "sample",
        "search_dt": now.strftime("%Y-%m-%d %H:%M:%S"),
        "routes": [
            {
                "rank": 1,
                "label": f"{departure_station.station_name} -> {arrival_station.station_name} / 샘플 경로",
                "route_types": ["sample"],
                "score": 208.0,
                "recommendation_cost": 92.0,
                "total_travel_minutes": 16.0,
                "transfer_count": 1,
                "weighted_average_congestion": 63.6,
                "weighted_average_congestion_level": "보통",
                "max_congestion_level": "다소혼잡",
                "path_stations": [
                    departure_station.station_name,
                    "중간 환승역",
                    arrival_station.station_name,
                ],
                "segment_rows": segment_rows,
            }
        ],
        "alternative_route": None,
        "failed_routes": [],
        "warning": "추천 API 실패로 샘플 데이터 모드로 표시합니다.",
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/assets/subway-map")
def subway_map_image() -> FileResponse:
    return FileResponse(DEFAULT_IMAGE_PATH)


@app.get("/api/map-data")
def map_data() -> dict[str, Any]:
    hotspots = load_station_hotspots()
    image_width, image_height = get_image_size(DEFAULT_IMAGE_PATH)
    return {
        "ok": True,
        "image": {
            "url": "/api/assets/subway-map",
            "width": image_width,
            "height": image_height,
        },
        "hotspots": hotspots.to_dict(orient="records"),
        "registered_hotspot_count": len(hotspots),
        "warning": (
            f"현재 좌표 등록 역 수가 {len(hotspots)}개로 적습니다. 좌표 등록을 더 진행하세요."
            if len(hotspots) < MIN_REGISTERED_HOTSPOT_WARNING_COUNT
            else None
        ),
    }


@app.post("/api/recommendations")
def recommendations(request: RecommendationRequest) -> dict[str, Any]:
    search_dt = request.search_dt or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        rank_result = rank_least_crowded_routes(
            start_station_name=request.departure_station.station_name_norm,
            end_station_name=request.arrival_station.station_name_norm,
            start_line=request.departure_station.line,
            end_line=request.arrival_station.line,
            search_dt=search_dt,
        )
        frontend_payload = to_frontend_ranked_routes_response(rank_result)
        if frontend_payload.get("ok"):
            route_lookup = {route["label"]: route for route in frontend_payload.get("routes", [])}
            for candidate in rank_result.get("ranked_routes", []):
                matched_timeline = (
                    candidate.get("result", {})
                    .get("congestion_result", {})
                    .get("matched_timeline", [])
                )
                label = candidate.get("label")
                if label in route_lookup:
                    route_lookup[label]["segment_rows"] = matched_timeline

            return {
                **frontend_payload,
                "mode": "live",
            }
    except Exception as exc:
        sample_payload = build_sample_route_payload(
            departure_station=request.departure_station,
            arrival_station=request.arrival_station,
        )
        sample_payload["error_detail"] = str(exc)
        return sample_payload

    return build_sample_route_payload(
        departure_station=request.departure_station,
        arrival_station=request.arrival_station,
    )
