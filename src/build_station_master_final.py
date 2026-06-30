from pathlib import Path

import pandas as pd


BASE_DIR = Path.cwd()

INPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step5.csv"
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "station_master.csv"
CONGESTION_ALIAS_PATH = BASE_DIR / "data" / "config" / "congestion_station_match_alias.csv"


REQUIRED_COLUMNS = [
    "line",
    "subway_id",
    "station_id",
    "station_name",
    "station_name_norm",
    "station_key",
    "external_code",
    "api_station_name",
]


def load_congestion_aliases() -> pd.DataFrame:
    if not CONGESTION_ALIAS_PATH.exists():
        return pd.DataFrame(
            columns=[
                "line",
                "alias_station_name",
                "alias_station_name_norm",
                "canonical_station_key",
                "reason",
            ]
        )

    alias_df = pd.read_csv(CONGESTION_ALIAS_PATH, encoding="utf-8-sig")

    required_alias_cols = [
        "line",
        "alias_station_name",
        "alias_station_name_norm",
        "canonical_station_key",
        "reason",
    ]
    missing_alias_cols = [col for col in required_alias_cols if col not in alias_df.columns]
    if missing_alias_cols:
        raise ValueError(
            f"Missing alias columns: {missing_alias_cols}\n"
            f"Current columns: {alias_df.columns.tolist()}"
        )

    for col in required_alias_cols:
        alias_df[col] = alias_df[col].fillna("").astype(str).str.strip()

    alias_df = alias_df[alias_df["canonical_station_key"] != ""].copy()
    return alias_df


def build_station_master_final() -> pd.DataFrame:
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Missing required columns: {missing_cols}\n"
            f"Current columns: {df.columns.tolist()}"
        )

    station_master = df[REQUIRED_COLUMNS].copy()
    station_master["source"] = "realtime_station_info"

    string_cols = [
        "line",
        "subway_id",
        "station_id",
        "station_name",
        "station_name_norm",
        "station_key",
        "api_station_name",
        "source",
    ]
    for col in string_cols:
        station_master[col] = station_master[col].fillna("").astype(str).str.strip()

    station_master["external_code"] = (
        station_master["external_code"].fillna("").astype(str).str.strip().replace("nan", "")
    )

    station_master = station_master.drop_duplicates(subset=["station_key"], keep="first")

    alias_df = load_congestion_aliases()
    alias_rows = pd.DataFrame(columns=station_master.columns)

    if not alias_df.empty:
        canonical_rows = station_master.merge(
            alias_df,
            left_on="station_key",
            right_on="canonical_station_key",
            how="right",
        )

        missing_canonical = canonical_rows[canonical_rows["station_key"].isna()]
        if not missing_canonical.empty:
            raise ValueError(
                "Some alias rows reference missing canonical_station_key values:\n"
                f"{missing_canonical[['line_y', 'alias_station_name', 'canonical_station_key']].to_string(index=False)}"
            )

        alias_rows = canonical_rows[
            [
                "line_x",
                "subway_id",
                "station_id",
                "external_code",
                "api_station_name",
                "alias_station_name",
                "alias_station_name_norm",
                "reason",
            ]
        ].copy()

        alias_rows = alias_rows.rename(
            columns={
                "line_x": "line",
                "alias_station_name": "station_name",
                "alias_station_name_norm": "station_name_norm",
            }
        )
        alias_rows["station_key"] = alias_rows["line"] + "_" + alias_rows["station_name_norm"]
        alias_rows["source"] = "congestion_station_alias"
        alias_rows = alias_rows[
            [
                "line",
                "subway_id",
                "station_id",
                "station_name",
                "station_name_norm",
                "station_key",
                "external_code",
                "api_station_name",
                "source",
            ]
        ]

    station_master = pd.concat([station_master, alias_rows], ignore_index=True)
    station_master = station_master.drop_duplicates(subset=["station_key"], keep="first")
    station_master = station_master.sort_values(by=["line", "station_name_norm"]).reset_index(drop=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    station_master.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"Saved station_master: {OUTPUT_PATH}")
    print(f"Rows: {len(station_master)}")
    print(f"Columns: {station_master.columns.tolist()}")

    if not alias_rows.empty:
        print()
        print("Added congestion match aliases:")
        print(alias_rows[["line", "station_name", "station_name_norm", "station_key", "api_station_name"]])

    return station_master


def validate_station_master(station_master: pd.DataFrame) -> None:
    print()
    print("Line counts:")
    print(station_master["line"].value_counts().sort_index())
    print()

    duplicated_count = station_master["station_key"].duplicated().sum()
    print("Duplicated station_key count:", duplicated_count)

    if duplicated_count > 0:
        print(
            station_master[
                station_master["station_key"].duplicated(keep=False)
            ].sort_values("station_key")
        )

    alias_rows = station_master[station_master["source"] == "congestion_station_alias"]
    print()
    print("Congestion alias row count:", len(alias_rows))
    if not alias_rows.empty:
        print(alias_rows[["line", "station_name", "station_name_norm", "station_key", "api_station_name"]])


if __name__ == "__main__":
    station_master_df = build_station_master_final()
    validate_station_master(station_master_df)
