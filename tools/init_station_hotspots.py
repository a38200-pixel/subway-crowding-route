from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
STATION_MASTER_PATH = BASE_DIR / "data" / "processed" / "station_master.csv"
HOTSPOTS_PATH = BASE_DIR / "data" / "processed" / "station_hotspots.csv"
TARGET_LINES = [f"{i}호선" for i in range(1, 10)]

OUTPUT_COLUMNS = [
    "station_key",
    "line",
    "station_name",
    "station_name_norm",
    "x",
    "y",
    "radius",
    "is_transfer",
    "enabled",
    "coord_status",
    "memo",
]


def load_station_master() -> pd.DataFrame:
    if not STATION_MASTER_PATH.exists():
        raise FileNotFoundError(f"station_master.csv not found: {STATION_MASTER_PATH}")

    df = pd.read_csv(STATION_MASTER_PATH)
    required_columns = ["station_key", "line", "station_name", "station_name_norm"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"station_master.csv missing columns: {missing_columns}")

    df = df[required_columns].copy()
    df = df[df["line"].isin(TARGET_LINES)].copy()
    df = df.drop_duplicates(subset=["station_key"]).reset_index(drop=True)

    transfer_counts = df.groupby("station_name_norm")["line"].nunique()
    df["is_transfer"] = df["station_name_norm"].map(transfer_counts).fillna(0).gt(1)
    return df


def build_default_hotspots(station_df: pd.DataFrame) -> pd.DataFrame:
    hotspots = station_df.copy()
    hotspots["x"] = pd.Series([pd.NA] * len(hotspots), dtype="Float64")
    hotspots["y"] = pd.Series([pd.NA] * len(hotspots), dtype="Float64")
    hotspots["radius"] = 35
    hotspots["enabled"] = False
    hotspots["coord_status"] = "pending"
    hotspots["memo"] = ""
    return hotspots[OUTPUT_COLUMNS]


def load_existing_hotspots() -> pd.DataFrame:
    if not HOTSPOTS_PATH.exists():
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    existing = pd.read_csv(HOTSPOTS_PATH)
    for column in OUTPUT_COLUMNS:
        if column not in existing.columns:
            existing[column] = pd.NA

    existing = existing[OUTPUT_COLUMNS].copy()
    existing = existing.drop_duplicates(subset=["station_key"], keep="last")
    return existing


def merge_hotspots(default_hotspots: pd.DataFrame, existing_hotspots: pd.DataFrame) -> pd.DataFrame:
    if existing_hotspots.empty:
        return default_hotspots.copy()

    merged = default_hotspots.merge(
        existing_hotspots,
        on="station_key",
        how="left",
        suffixes=("_new", "_old"),
    )

    result = pd.DataFrame()
    result["station_key"] = merged["station_key"]

    # Master data stays authoritative for station identity fields.
    for column in ["line", "station_name", "station_name_norm", "is_transfer"]:
        result[column] = merged[f"{column}_new"]

    # Preserve existing coordinate and status values when present.
    for column in ["x", "y", "radius", "enabled", "coord_status", "memo"]:
        result[column] = merged[f"{column}_old"].where(
            merged[f"{column}_old"].notna(),
            merged[f"{column}_new"],
        )

    result = result[OUTPUT_COLUMNS]
    result["coord_status"] = result["coord_status"].fillna("pending")
    result["memo"] = result["memo"].fillna("")
    result["radius"] = pd.to_numeric(result["radius"], errors="coerce").fillna(35).astype(int)
    result["enabled"] = result["enabled"].fillna(False).astype(bool)
    result["is_transfer"] = result["is_transfer"].fillna(False).astype(bool)
    result = result.sort_values(["line", "station_name_norm", "station_name"]).reset_index(drop=True)
    return result


def print_summary(hotspots: pd.DataFrame) -> None:
    total_count = len(hotspots)
    pending_count = hotspots["coord_status"].fillna("pending").eq("pending").sum()
    confirmed_count = hotspots["coord_status"].fillna("").eq("confirmed").sum()

    print(f"Saved hotspot file: {HOTSPOTS_PATH}")
    print(f"Total stations: {total_count}")
    print(f"Pending: {pending_count}")
    print(f"Confirmed: {confirmed_count}")


def main() -> None:
    station_df = load_station_master()
    default_hotspots = build_default_hotspots(station_df)
    existing_hotspots = load_existing_hotspots()

    merged_hotspots = merge_hotspots(default_hotspots, existing_hotspots)

    HOTSPOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged_hotspots.to_csv(HOTSPOTS_PATH, index=False, encoding="utf-8-sig")

    print_summary(merged_hotspots)


if __name__ == "__main__":
    main()
