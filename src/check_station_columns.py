from pathlib import Path
import pandas as pd


# 현재 프로젝트 루트 기준
BASE_DIR = Path.cwd()

RAW_PATH = BASE_DIR / "data" / "raw" / "realtime_station_info.xlsx"

# 2단계 결과 확인용 저장 파일
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "station_columns_step2.csv"

    
# 1. 엑셀 파일 읽기
df = pd.read_excel(RAW_PATH)

print("=" * 60)
print("1. 원본 데이터 확인")
print("=" * 60)
print("파일 경로:", RAW_PATH)
print("데이터 크기:", df.shape)
print("원본 컬럼:", df.columns.tolist())
print()
print(df.head())


# 2. 필요한 컬럼만 선택
df_step2 = df[["호선이름", "SUBWAY_ID", "STATN_ID", "STATN_NM"]].copy()


# 3. 컬럼명 변경
df_step2 = df_step2.rename(
    columns={
        "호선이름": "line",
        "SUBWAY_ID": "subway_id",
        "STATN_ID": "station_id",
        "STATN_NM": "station_name",
    }
)


# 4. 문자열 정리
# 코드값은 숫자로 계산할 게 아니라 식별자이므로 문자열로 관리
df_step2["line"] = df_step2["line"].astype(str).str.strip()
df_step2["subway_id"] = df_step2["subway_id"].astype(str).str.strip()
df_step2["station_id"] = df_step2["station_id"].astype(str).str.strip()
df_step2["station_name"] = df_step2["station_name"].astype(str).str.strip()


# 5. 이번 파일에 없는 external_code 컬럼 생성
df_step2["external_code"] = ""


# 6. API 호출용 역명 컬럼 생성
# 처음에는 station_name과 동일하게 둔다.
# 예외 역명은 나중에 station_alias.csv에서 따로 처리한다.
df_step2["api_station_name"] = df_step2["station_name"]


# 7. 컬럼 순서 정리
df_step2 = df_step2[
    [
        "line",
        "subway_id",
        "station_id",
        "station_name",
        "external_code",
        "api_station_name",
    ]
]


# 8. 결과 저장
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
df_step2.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")


print()
print("=" * 60)
print("2. 컬럼 정리 결과")
print("=" * 60)
print("저장 경로:", OUTPUT_PATH)
print("정리 후 크기:", df_step2.shape)
print("정리 후 컬럼:", df_step2.columns.tolist())
print()
print(df_step2.head(20))