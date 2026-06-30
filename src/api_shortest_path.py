from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
import os
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener, HTTPSHandler
BASE_DIR = Path.cwd()
ENV_PATH = BASE_DIR / ".env"
STATION_MASTER_PATH = BASE_DIR / "data" / "processed" / "station_master.csv"
DEFAULT_ENDPOINT = "https://apis.data.go.kr/B553766/path2/getShtrmPath2"
NO_PROXY_OPENER = build_opener(
    ProxyHandler({}),
    HTTPSHandler(context=ssl._create_unverified_context()),
)

ROUTE_TYPE_MAP = {
    "min_time": "duration",
    "min_distance": "distance",
    "min_transfer": "transfer",
}


def load_env_file(env_path: Path = ENV_PATH) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def get_shortest_path_api_key() -> str:
    load_env_file()
    api_key = os.getenv("SEOUL_METRO_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SEOUL_METRO_KEY is not set.")
    return api_key


def resolve_route_type(route_type: str) -> str:
    normalized = route_type.strip().lower()
    if normalized not in ROUTE_TYPE_MAP:
        raise ValueError(
            "route_type must be one of: min_time, min_distance, min_transfer"
        )
    return ROUTE_TYPE_MAP[normalized]


def _now_search_dt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_station_master() -> list[dict[str, str]]:
    if not STATION_MASTER_PATH.exists():
        raise FileNotFoundError(f"station_master.csv not found: {STATION_MASTER_PATH}")

    with STATION_MASTER_PATH.open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    required_cols = ["line", "station_id", "station_name", "station_name_norm"]
    missing_cols = [col for col in required_cols if col not in rows[0]]
    if missing_cols:
        raise ValueError(
            f"station_master.csv is missing required columns: {missing_cols}"
        )

    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = {key: (value or "").strip() for key, value in row.items()}
        normalized["shortest_path_station_code"] = normalized["station_id"][-4:]
        normalized_rows.append(normalized)

    return normalized_rows


def resolve_station_code(
    station_name: str,
    *,
    line: str | None = None,
    station_df: list[dict[str, str]] | None = None,
) -> str:
    rows = station_df if station_df is not None else load_station_master()
    station_name = station_name.strip()
    line = line.strip() if line else None

    target = [
        row for row in rows
        if row["station_name_norm"] == station_name and (line is None or row["line"] == line)
    ]

    if not target:
        raise ValueError(f"Station not found in station_master: {station_name}")

    deduped_by_code: dict[str, dict[str, str]] = {}
    for row in target:
        deduped_by_code[row["shortest_path_station_code"]] = row

    deduped = list(deduped_by_code.values())
    if len(deduped) > 1:
        lines = sorted({row["line"] for row in deduped})
        raise ValueError(
            f"Ambiguous station name '{station_name}'. Specify line. Candidates: {lines}"
        )

    return deduped[0]["shortest_path_station_code"]


def build_request_params(
    start_station: str,
    end_station: str,
    route_type: str,
    *,
    data_type: str = "JSON",
    search_dt: str | None = None,
    excl_trf_stns: str = "",
    thrgh_stns: str = "",
    sch_incl_yn: str = "Y",
    station_value_type: str = "name",
) -> dict[str, Any]:
    params = {
        "serviceKey": get_shortest_path_api_key(),
        "dataType": data_type,
        "dptreStn": start_station,
        "arvlStn": end_station,
        "searchDt": search_dt or _now_search_dt(),
        "searchType": resolve_route_type(route_type),
    }

    if excl_trf_stns:
        params["exclTrfstns"] = excl_trf_stns
    if thrgh_stns:
        params["thrghStns"] = thrgh_stns
    if sch_incl_yn:
        params["schInclYn"] = sch_incl_yn
    if station_value_type:
        params["stationValueType"] = station_value_type

    return params


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_shortest_path_response(
    raw_response: Any,
    *,
    start_station: str,
    end_station: str,
    route_type: str,
) -> dict[str, Any]:
    header = raw_response.get("header") if isinstance(raw_response, dict) else {}
    body = raw_response.get("body") if isinstance(raw_response, dict) else {}
    if not isinstance(header, dict):
        header = {}
    if not isinstance(body, dict):
        body = {}
    paths = body.get("paths", []) if isinstance(body, dict) else []

    stations: list[str] = []
    segments: list[dict[str, Any]] = []

    for item in paths:
        if not isinstance(item, dict):
            continue

        depart = item.get("dptreStn", {}) or {}
        arrive = item.get("arvlStn", {}) or {}

        depart_name = depart.get("stnNm")
        arrive_name = arrive.get("stnNm")

        if isinstance(depart_name, str):
            stations.append(depart_name)
        if isinstance(arrive_name, str):
            stations.append(arrive_name)

        segments.append(
            {
                "from_station": depart_name,
                "from_station_code": depart.get("stnCd"),
                "to_station": arrive_name,
                "to_station_code": arrive.get("stnCd"),
                "line": depart.get("lineNm") or arrive.get("lineNm"),
                "branch_line": depart.get("brlnNm") or arrive.get("brlnNm"),
                "distance": item.get("stnSctnDstc"),
                "travel_time": item.get("reqHr"),
                "waiting_time": item.get("wtngHr"),
                "terminal_station": item.get("tmnlStnNm"),
                "terminal_station_code": item.get("tmnlStnCd"),
                "direction": item.get("upbdnbSe"),
                "train_no": item.get("trainno"),
                "train_departure_time": item.get("trainDptreTm"),
                "train_arrival_time": item.get("trainArvlTm"),
                "is_transfer": item.get("trsitYn"),
                "is_express": item.get("etrnYn"),
                "is_nonstop": item.get("nonstopYn"),
            }
        )

    return {
        "result_code": header.get("resultCode"),
        "result_message": header.get("resultMsg"),
        "start_station": start_station,
        "end_station": end_station,
        "route_type": route_type,
        "search_type": body.get("searchType"),
        "total_distance": body.get("totalDstc"),
        "total_time": body.get("totalReqHr"),
        "fare": body.get("totalCardCrg"),
        "transfer_count": body.get("trsitNmtm"),
        "transfer_stations": body.get("trfstnNms", []),
        "excluded_transfer_stations": body.get("exclTrfstns", []),
        "through_stations": body.get("thrghStns", []),
        "schedule_included": body.get("schInclYn"),
        "stations": _dedupe_keep_order(stations),
        "segments": segments,
    }


def save_path_result(
    save_path: str | Path,
    *,
    request_url: str,
    request_params: dict[str, Any],
    raw_response: Any,
    normalized_response: dict[str, Any] | None,
) -> None:
    payload = {
        "request_url": request_url,
        "request_params": request_params,
        "raw_response": raw_response,
        "normalized_response": normalized_response,
    }
    path = Path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_shortest_path(
    start_station: str,
    end_station: str,
    route_type: str = "min_time",
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: int = 15,
    data_type: str = "JSON",
    search_dt: str | None = None,
    excl_trf_stns: str = "",
    thrgh_stns: str = "",
    sch_incl_yn: str = "Y",
    station_value_type: str = "name",
    save_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        params = build_request_params(
            start_station=start_station,
            end_station=end_station,
            route_type=route_type,
            data_type=data_type,
            search_dt=search_dt,
            excl_trf_stns=excl_trf_stns,
            thrgh_stns=thrgh_stns,
            sch_incl_yn=sch_incl_yn,
            station_value_type=station_value_type,
        )
    except Exception as exc:
        return {
            "ok": False,
            "message": "경로 조회 실패",
            "error": str(exc),
            "raw_response": None,
            "normalized_response": None,
        }

    request_url = f"{endpoint}?{urlencode(params)}"

    try:
        with NO_PROXY_OPENER.open(request_url, timeout=timeout) as response:
            status_code = getattr(response, "status", 200)
            body_text = response.read().decode("utf-8", errors="replace")

        try:
            raw_response: Any = json.loads(body_text)
        except ValueError:
            raw_response = {
                "status_code": status_code,
                "text": body_text,
            }

        normalized_response = normalize_shortest_path_response(
            raw_response,
            start_station=start_station,
            end_station=end_station,
            route_type=route_type,
        )

        result = {
            "ok": True,
            "message": "success",
            "request_url": request_url,
            "request_params": params,
            "raw_response": raw_response,
            "normalized_response": normalized_response,
        }

        if save_path:
            save_path_result(
                save_path,
                request_url=request_url,
                request_params=params,
                raw_response=raw_response,
                normalized_response=normalized_response,
            )

        return result

    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raw_response = {
            "status_code": exc.code,
            "reason": exc.reason,
            "text": error_body,
        }
        result = {
            "ok": False,
            "message": "경로 조회 실패",
            "error": f"HTTP Error {exc.code}: {exc.reason}",
            "request_url": request_url,
            "request_params": params,
            "raw_response": raw_response,
            "normalized_response": None,
        }
        if save_path:
            save_path_result(
                save_path,
                request_url=request_url,
                request_params=params,
                raw_response=raw_response,
                normalized_response=None,
            )
        return result

    except (URLError, TimeoutError, ValueError) as exc:
        result = {
            "ok": False,
            "message": "경로 조회 실패",
            "error": str(exc),
            "request_url": request_url,
            "request_params": params,
            "raw_response": None,
            "normalized_response": None,
        }
        if save_path:
            save_path_result(
                save_path,
                request_url=request_url,
                request_params=params,
                raw_response=None,
                normalized_response=None,
            )
        return result


def fetch_shortest_path_by_name(
    start_station_name: str,
    end_station_name: str,
    route_type: str = "min_time",
    *,
    start_line: str | None = None,
    end_line: str | None = None,
    search_dt: str | None = None,
    excl_trf_stns: str = "",
    thrgh_stns: str = "",
    sch_incl_yn: str = "Y",
    save_path: str | Path | None = None,
) -> dict[str, Any]:
    station_df = load_station_master()
    start_code = resolve_station_code(
        start_station_name,
        line=start_line,
        station_df=station_df,
    )
    end_code = resolve_station_code(
        end_station_name,
        line=end_line,
        station_df=station_df,
    )

    return fetch_shortest_path(
        start_station=start_code,
        end_station=end_code,
        route_type=route_type,
        search_dt=search_dt,
        excl_trf_stns=excl_trf_stns,
        thrgh_stns=thrgh_stns,
        sch_incl_yn=sch_incl_yn,
        station_value_type="code",
        save_path=save_path,
    )


def get_seoul_metro_shortest_path(
    start_station: str,
    end_station: str,
    route_type: str = "min_time",
    save_path: str | Path | None = None,
) -> dict[str, Any]:
    return fetch_shortest_path_by_name(
        start_station_name=start_station,
        end_station_name=end_station,
        route_type=route_type,
        save_path=save_path,
    )


if __name__ == "__main__":
    result = fetch_shortest_path_by_name(
        start_station_name="강남",
        end_station_name="홍대입구",
        route_type="min_time",
        start_line="2호선",
        end_line="2호선",
        search_dt="2026-05-22 12:30:30",
        save_path="data/raw/api_samples/shortestpath_runtime.json",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
