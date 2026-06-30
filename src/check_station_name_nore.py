from pathlib import Path
import re

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

INPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step2.csv"
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step3.csv"


# =========================================================
# 2. 역명 정규화 함수
# =========================================================

def normalize_station_name(name: str) -> str:
    """
    역명을 데이터 매칭용 표준 이름으로 정규화한다.

    예:
    공릉(서울산업대입구) -> 공릉
    천호(풍납토성) -> 천호
    동대문역 -> 동대문
    서울 역 -> 서울
    """
    if pd.isna(name):
        return ""

    # 문자열 변환 + 앞뒤 공백 제거
    name = str(name).strip()

    # 괄호 안 부역명 제거
    # 예: 공릉(서울산업대입구) -> 공릉
    name = re.sub(r"\(.*?\)", "", name)

    # 모든 공백 제거
    # 예: 서울 역 -> 서울역
    name = re.sub(r"\s+", "", name)

    # 끝에 붙은 '역' 제거
    # 예: 동대문역 -> 동대문
    if name.endswith("역"):
        name = name[:-1]

    # 하이픈, 언더바 제거
    name = name.replace("-", "").replace("_", "")

    return name


# =========================================================
# 3. 데이터 불러오기
# =========================================================

df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")

print("=" * 60)
print("1. 2단계 결과 파일 로드")
print("=" * 60)
print("입력 파일:", INPUT_PATH)
print("데이터 크기:", df.shape)
print("컬럼:", df.columns.tolist())
print()
print(df.head())


# =========================================================
# 4. station_name_norm 컬럼 생성
# =========================================================

df["station_name_norm"] = df["station_name"].apply(normalize_station_name)


# =========================================================
# 5. 컬럼 순서 정리
# =========================================================

df = df[
    [
        "line",
        "subway_id",
        "station_id",
        "station_name",
        "station_name_norm",
        "external_code",
        "api_station_name",
    ]
]


# =========================================================
# 6. 결과 저장
# =========================================================

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

print()
print("=" * 60)
print("2. 3단계 station_name_norm 생성 완료")
print("=" * 60)
print("저장 경로:", OUTPUT_PATH)
print("데이터 크기:", df.shape)
print("컬럼:", df.columns.tolist())
print()
print(df.head(20))


# =========================================================
# 7. 정규화 결과 검증
# =========================================================

print()
print("=" * 60)
print("3. 정규화 전/후가 다른 역명 확인")
print("=" * 60)

changed_df = df[df["station_name"] != df["station_name_norm"]]

print("변경된 역 개수:", len(changed_df))
print()
print(changed_df[["line", "station_name", "station_name_norm"]].head(50))


print()
print("=" * 60)
print("4. station_name_norm 중복 확인")
print("=" * 60)

duplicated_df = df[df.duplicated(subset=["line", "station_name_norm"], keep=False)]

print("line + station_name_norm 기준 중복 개수:", len(duplicated_df))
print()
print(duplicated_df[["line", "station_name", "station_name_norm"]].sort_values(["line", "station_name_norm"]).head(50))