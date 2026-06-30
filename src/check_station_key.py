from pathlib import Path

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

INPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step3.csv"
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step4.csv"


# =========================================================
# 2. 데이터 불러오기
# =========================================================

df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")

print("=" * 60)
print("1. 3단계 결과 파일 로드")
print("=" * 60)
print("입력 파일:", INPUT_PATH)
print("데이터 크기:", df.shape)
print("컬럼:", df.columns.tolist())
print()
print(df.head())


# =========================================================
# 3. 필수 컬럼 확인
# =========================================================

required_cols = [
    "line",
    "subway_id",
    "station_id",
    "station_name",
    "station_name_norm",
    "external_code",
    "api_station_name",
]

missing_cols = [col for col in required_cols if col not in df.columns]

if missing_cols:
    raise ValueError(
        f"필수 컬럼이 없습니다: {missing_cols}\n"
        f"현재 컬럼: {df.columns.tolist()}"
    )


# =========================================================
# 4. line, station_name_norm 문자열 정리
# =========================================================

df["line"] = df["line"].astype(str).str.strip()
df["station_name_norm"] = df["station_name_norm"].astype(str).str.strip()


# =========================================================
# 5. station_key 생성
# =========================================================

df["station_key"] = df["line"] + "_" + df["station_name_norm"]


# =========================================================
# 6. 컬럼 순서 정리
# =========================================================

df = df[
    [
        "line",
        "subway_id",
        "station_id",
        "station_name",
        "station_name_norm",
        "station_key",
        "external_code",
        "api_station_name",
    ]
]


# =========================================================
# 7. 결과 저장
# =========================================================

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

print()
print("=" * 60)
print("2. 4단계 station_key 생성 완료")
print("=" * 60)
print("저장 경로:", OUTPUT_PATH)
print("데이터 크기:", df.shape)
print("컬럼:", df.columns.tolist())
print()
print(df.head(20))


# =========================================================
# 8. station_key 중복 확인
# =========================================================

print()
print("=" * 60)
print("3. station_key 중복 확인")
print("=" * 60)

duplicated_df = df[df.duplicated(subset=["station_key"], keep=False)]

print("중복 station_key 개수:", len(duplicated_df))
print()

if len(duplicated_df) > 0:
    print("중복 station_key 목록:")
    print(
        duplicated_df[
            [
                "line",
                "subway_id",
                "station_id",
                "station_name",
                "station_name_norm",
                "station_key",
            ]
        ].sort_values("station_key").head(100)
    )
else:
    print("중복 station_key가 없습니다.")


# =========================================================
# 9. 환승역 / 동명이역 확인
# =========================================================

print()
print("=" * 60)
print("4. 같은 역명이 여러 호선에 있는 경우 확인")
print("=" * 60)

transfer_like_df = df[df.duplicated(subset=["station_name_norm"], keep=False)]

print("여러 호선에 존재하는 station_name_norm 개수:", transfer_like_df["station_name_norm"].nunique())
print()

print(
    transfer_like_df[
        [
            "line",
            "station_name",
            "station_name_norm",
            "station_key",
        ]
    ].sort_values(["station_name_norm", "line"]).head(100)
)