from pathlib import Path

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

INPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step4.csv"

CONFIG_DIR = BASE_DIR / "data" / "config"
ALIAS_PATH = CONFIG_DIR / "station_alias.csv"

OUTPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step5.csv"


# =========================================================
# 2. 기본 alias 파일 생성 함수
# =========================================================

def create_default_alias_file() -> None:
    """
    station_alias.csv가 없으면 기본 alias 파일을 생성한다.
    이미 파일이 있으면 덮어쓰지 않는다.
    """

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if ALIAS_PATH.exists():
        print("기존 station_alias.csv 파일이 있습니다.")
        print("새로 만들지 않고 기존 파일을 사용합니다.")
        print("경로:", ALIAS_PATH)
        return

    alias_df = pd.DataFrame(
        [
            {
                "line": "6호선",
                "station_name_norm": "응암",
                "api_station_name": "응암순환",
                "reason": "실시간 도착 API 호출용 예외",
            },
            {
                "line": "7호선",
                "station_name_norm": "공릉",
                "api_station_name": "공릉(서울산업대입구)",
                "reason": "부역명 포함 필요",
            },
            {
                "line": "8호선",
                "station_name_norm": "남한산성입구",
                "api_station_name": "남한산성입구(성남법원, 검찰청)",
                "reason": "부역명 포함 필요",
            },
            {
                "line": "3호선",
                "station_name_norm": "대모산입구",
                "api_station_name": "대모산",
                "reason": "API 호출명 차이",
            },
            {
                "line": "5호선",
                "station_name_norm": "천호",
                "api_station_name": "천호(풍납토성)",
                "reason": "부역명 포함 필요",
            },
            {
                "line": "8호선",
                "station_name_norm": "몽촌토성",
                "api_station_name": "몽촌토성(평화의문)",
                "reason": "부역명 포함 필요",
            },
        ]
    )

    alias_df.to_csv(ALIAS_PATH, index=False, encoding="utf-8-sig")

    print("기본 station_alias.csv 생성 완료")
    print("저장 경로:", ALIAS_PATH)


# =========================================================
# 3. alias 적용
# =========================================================

def apply_station_alias() -> pd.DataFrame:
    # 1) alias 파일 생성
    create_default_alias_file()

    # 2) 4단계 결과 파일 로드
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")

    print("=" * 60)
    print("1. 4단계 station_key 결과 파일 로드")
    print("=" * 60)
    print("입력 파일:", INPUT_PATH)
    print("데이터 크기:", df.shape)
    print("컬럼:", df.columns.tolist())
    print()
    print(df.head())

    # 3) alias 파일 로드
    alias_df = pd.read_csv(ALIAS_PATH, encoding="utf-8-sig")

    print()
    print("=" * 60)
    print("2. station_alias.csv 로드")
    print("=" * 60)
    print("alias 파일:", ALIAS_PATH)
    print("alias 크기:", alias_df.shape)
    print("alias 컬럼:", alias_df.columns.tolist())
    print()
    print(alias_df)

    # 4) 필수 컬럼 확인
    required_df_cols = [
        "line",
        "subway_id",
        "station_id",
        "station_name",
        "station_name_norm",
        "station_key",
        "external_code",
        "api_station_name",
    ]

    missing_df_cols = [col for col in required_df_cols if col not in df.columns]

    if missing_df_cols:
        raise ValueError(
            f"station_columns_step4.csv에 필수 컬럼이 없습니다: {missing_df_cols}\n"
            f"현재 컬럼: {df.columns.tolist()}"
        )

    required_alias_cols = [
        "line",
        "station_name_norm",
        "api_station_name",
        "reason",
    ]

    missing_alias_cols = [
        col for col in required_alias_cols if col not in alias_df.columns
    ]

    if missing_alias_cols:
        raise ValueError(
            f"station_alias.csv에 필수 컬럼이 없습니다: {missing_alias_cols}\n"
            f"현재 컬럼: {alias_df.columns.tolist()}"
        )

    # 5) 문자열 정리
    df["line"] = df["line"].astype(str).str.strip()
    df["station_name_norm"] = df["station_name_norm"].astype(str).str.strip()
    df["api_station_name"] = df["api_station_name"].astype(str).str.strip()

    alias_df["line"] = alias_df["line"].astype(str).str.strip()
    alias_df["station_name_norm"] = alias_df["station_name_norm"].astype(str).str.strip()
    alias_df["api_station_name"] = alias_df["api_station_name"].astype(str).str.strip()

    # 6) alias 적용 전 원본 api_station_name 보존
    df["api_station_name_before_alias"] = df["api_station_name"]

    # 7) line + station_name_norm 기준으로 alias 병합
    df = df.merge(
        alias_df[["line", "station_name_norm", "api_station_name", "reason"]],
        on=["line", "station_name_norm"],
        how="left",
        suffixes=("", "_alias"),
    )

    # 8) alias가 있으면 api_station_name을 alias 값으로 교체
    df["api_station_name"] = df["api_station_name_alias"].fillna(
        df["api_station_name"]
    )

    # 9) alias 적용 여부 컬럼 생성
    df["is_alias_applied"] = df["api_station_name_alias"].notna()

    # 10) alias reason 정리
    df["alias_reason"] = df["reason"].fillna("")

    # 11) 불필요한 임시 컬럼 제거
    df = df.drop(columns=["api_station_name_alias", "reason"])

    # 12) 컬럼 순서 정리
    df = df[
        [
            "line",
            "subway_id",
            "station_id",
            "station_name",
            "station_name_norm",
            "station_key",
            "external_code",
            "api_station_name_before_alias",
            "api_station_name",
            "is_alias_applied",
            "alias_reason",
        ]
    ]

    # 13) 결과 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print()
    print("=" * 60)
    print("3. alias 적용 완료")
    print("=" * 60)
    print("저장 경로:", OUTPUT_PATH)
    print("데이터 크기:", df.shape)
    print("컬럼:", df.columns.tolist())
    print()
    print(df.head(20))

    return df


# =========================================================
# 4. alias 적용 결과 검증
# =========================================================

def validate_alias_result(df: pd.DataFrame) -> None:
    print()
    print("=" * 60)
    print("4. alias 적용 결과 검증")
    print("=" * 60)

    alias_applied_df = df[df["is_alias_applied"] == True]

    print("alias 적용된 역 개수:", len(alias_applied_df))
    print()

    if len(alias_applied_df) > 0:
        print("alias 적용된 역 목록:")
        print(
            alias_applied_df[
                [
                    "line",
                    "station_name",
                    "station_name_norm",
                    "api_station_name_before_alias",
                    "api_station_name",
                    "alias_reason",
                ]
            ]
        )
    else:
        print("alias가 적용된 역이 없습니다.")
        print("station_alias.csv의 line, station_name_norm 값이 station_columns_step4.csv와 맞는지 확인하세요.")

    print()
    print("=" * 60)
    print("5. alias 파일에는 있는데 station_master에는 없는 항목 확인")
    print("=" * 60)

    alias_df = pd.read_csv(ALIAS_PATH, encoding="utf-8-sig")

    # station_key 형태로 비교
    df_keys = set(df["line"] + "_" + df["station_name_norm"])
    alias_keys = set(alias_df["line"] + "_" + alias_df["station_name_norm"])

    missing_alias_keys = alias_keys - df_keys

    if len(missing_alias_keys) == 0:
        print("alias 파일의 모든 항목이 station 데이터에 존재합니다.")
    else:
        print("alias 파일에는 있지만 station 데이터에는 없는 항목:")
        for key in sorted(missing_alias_keys):
            print("-", key)


# =========================================================
# 5. 실행
# =========================================================

if __name__ == "__main__":
    result_df = apply_station_alias()
    validate_alias_result(result_df)