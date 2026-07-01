from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_PATH = BASE_DIR / "data" / "map" / "seoul_subway_map_ko.jpg"
DEFAULT_HOTSPOTS_PATH = BASE_DIR / "data" / "processed" / "station_hotspots.csv"
DEFAULT_STATION_MASTER_PATH = BASE_DIR / "data" / "processed" / "station_master.csv"


def _normalize_bool(series: pd.Series) -> pd.Series:
    return (
        series.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y"})
    )


def get_image_size(image_path: Path = DEFAULT_IMAGE_PATH) -> tuple[int, int]:
    if not image_path.exists():
        raise FileNotFoundError(f"Map image not found: {image_path}")

    with Image.open(image_path) as img:
        return img.size


def load_station_hotspots(
    hotspots_path: Path = DEFAULT_HOTSPOTS_PATH,
    station_master_path: Path = DEFAULT_STATION_MASTER_PATH,
) -> pd.DataFrame:
    if not hotspots_path.exists():
        raise FileNotFoundError(f"station_hotspots.csv not found: {hotspots_path}")
    if not station_master_path.exists():
        raise FileNotFoundError(f"station_master.csv not found: {station_master_path}")

    hotspots = pd.read_csv(hotspots_path)
    station_master = pd.read_csv(station_master_path)

    required_hotspot_columns = [
        "station_key",
        "line",
        "station_name",
        "station_name_norm",
        "x",
        "y",
        "radius",
        "enabled",
        "coord_status",
    ]
    missing_hotspot_columns = [col for col in required_hotspot_columns if col not in hotspots.columns]
    if missing_hotspot_columns:
        raise ValueError(f"station_hotspots.csv missing columns: {missing_hotspot_columns}")

    required_station_columns = ["station_key", "line", "station_name", "station_name_norm"]
    missing_station_columns = [col for col in required_station_columns if col not in station_master.columns]
    if missing_station_columns:
        raise ValueError(f"station_master.csv missing columns: {missing_station_columns}")

    station_master = station_master[required_station_columns].drop_duplicates(subset=["station_key"])
    hotspots["enabled"] = _normalize_bool(hotspots["enabled"])
    hotspots["coord_status"] = hotspots["coord_status"].fillna("").astype(str).str.strip().str.lower()
    hotspots["x"] = pd.to_numeric(hotspots["x"], errors="coerce")
    hotspots["y"] = pd.to_numeric(hotspots["y"], errors="coerce")
    hotspots["radius"] = pd.to_numeric(hotspots["radius"], errors="coerce").fillna(35)

    hotspots = hotspots.merge(
        station_master,
        on="station_key",
        how="left",
        suffixes=("", "_master"),
    )

    for column in ["line", "station_name", "station_name_norm"]:
        hotspots[column] = hotspots[column].fillna(hotspots[f"{column}_master"])

    filtered = hotspots[
        hotspots["enabled"]
        & hotspots["coord_status"].eq("confirmed")
        & hotspots["x"].notna()
        & hotspots["y"].notna()
    ].copy()

    filtered = filtered[
        ["station_key", "line", "station_name", "station_name_norm", "x", "y", "radius"]
    ].sort_values(["line", "station_name"])
    filtered.reset_index(drop=True, inplace=True)
    return filtered
