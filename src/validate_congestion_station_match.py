"""혼잡도 CSV와 station_master의 역 매칭 상태를 검증하는 스크립트."""

from pathlib import Path
import re

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

CONGESTION_PATH = BASE_DIR / "data" / "processed" / "congestion_long.csv"
STATION_MASTER_PATH = BASE_DIR / "data" / "processed" / "station_master.csv"

OUTPUT_PATH = BASE_DIR / "data" / "processed" / "congestion_long_with_station_key.csv"
UNMATCHED_OUTPUT_PATH = BASE_DIR / "data" / "processed" / "unmatched_congestion_stations.csv"


# =========================================================
# 2. 역명 정규화 함수
# =========================================================

# 역명을 비교용 표준 형태로 정규화한다.
def normalize_station_name(name: str) -> str:
    if pd.isna(name):
        return ""

    name = str(name).strip()

    # 괄호 안 부역명 제거
    name = re.sub(r"\(.*?\)", "", name)

    # 공백 제거
    name = re.sub(r"\s+", "", name)

    # 끝의 '역' 제거
    if name.endswith("역"):
        name = name[:-1]

    # 일부 특수문자 제거
    name = name.replace("-", "").replace("_", "")

    return name


# =========================================================
# 3. 호선명 정리 함수
# =========================================================

# 호선명을 비교용 표준 형태로 정규화한다.
def normalize_line_name(line: str) -> str:
    if pd.isna(line):
        return ""

    line = str(line).strip().replace(" ", "")

    if line.isdigit():
        return f"{int(line)}호선"

    match = re.match(r"^0?(\d+)호선$", line)
    if match:
        return f"{int(match.group(1))}호선"

    return line


# =========================================================
# 4. 매칭 검증
# =========================================================

# 혼잡도 데이터의 station_key가 station_master와 정확히 맞는지 점검한다.
def validate_match() -> None:
    congestion_df = pd.read_csv(CONGESTION_PATH, encoding="utf-8-sig")
    station_df = pd.read_csv(STATION_MASTER_PATH, encoding="utf-8-sig")

    print("=" * 60)
    print("1. 파일 로드 완료")
    print("=" * 60)
    print("혼잡도 데이터:", CONGESTION_PATH)
    print("혼잡도 크기:", congestion_df.shape)
    print("혼잡도 컬럼:", congestion_df.columns.tolist())
    print()
    print("역 마스터:", STATION_MASTER_PATH)
    print("역 마스터 크기:", station_df.shape)
    print("역 마스터 컬럼:", station_df.columns.tolist())
    print()

    # =====================================================
    # 1) 혼잡도 데이터에 station_name_norm 생성
    # =====================================================

    congestion_df["line"] = congestion_df["line"].apply(normalize_line_name)
    congestion_df["station_name_norm"] = congestion_df["station_name"].apply(
        normalize_station_name
    )

    # =====================================================
    # 2) 혼잡도 데이터에 station_key 생성
    # =====================================================

    congestion_df["station_key"] = (
        congestion_df["line"] + "_" + congestion_df["station_name_norm"]
    )

    # =====================================================
    # 3) station_master의 key 집합 생성
    # =====================================================

    station_keys = set(station_df["station_key"].astype(str))

    # =====================================================
    # 4) 매칭 여부 확인
    # =====================================================

    congestion_df["is_station_matched"] = congestion_df["station_key"].isin(station_keys)

    total_count = len(congestion_df)
    matched_count = congestion_df["is_station_matched"].sum()
    unmatched_count = total_count - matched_count

    print("=" * 60)
    print("2. 전체 매칭 결과")
    print("=" * 60)
    print("전체 행 개수:", total_count)
    print("매칭 성공 행 개수:", matched_count)
    print("매칭 실패 행 개수:", unmatched_count)
    print("매칭 성공률:", round(matched_count / total_count * 100, 2), "%")
    print()

    # =====================================================
    # 5) 고유 역 기준 매칭 확인
    # =====================================================

    congestion_station_keys = congestion_df[
        ["line", "station_name", "station_name_norm", "station_key"]
    ].drop_duplicates()

    congestion_station_keys["is_station_matched"] = congestion_station_keys[
        "station_key"
    ].isin(station_keys)

    unique_total = len(congestion_station_keys)
    unique_matched = congestion_station_keys["is_station_matched"].sum()
    unique_unmatched = unique_total - unique_matched

    print("=" * 60)
    print("3. 고유 역 기준 매칭 결과")
    print("=" * 60)
    print("혼잡도 데이터 고유 역 개수:", unique_total)
    print("매칭 성공 역 개수:", unique_matched)
    print("매칭 실패 역 개수:", unique_unmatched)
    print("고유 역 매칭 성공률:", round(unique_matched / unique_total * 100, 2), "%")
    print()

    # =====================================================
    # 6) 매칭 실패 역 목록 저장
    # =====================================================

    unmatched_stations = congestion_station_keys[
        congestion_station_keys["is_station_matched"] == False
    ].sort_values(["line", "station_name_norm"])

    unmatched_stations.to_csv(
        UNMATCHED_OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig"
    )

    print("=" * 60)
    print("4. 매칭 실패 역 목록")
    print("=" * 60)

    if len(unmatched_stations) == 0:
        print("매칭 실패 역이 없습니다.")
    else:
        print(unmatched_stations)
        print()
        print("매칭 실패 목록 저장 경로:", UNMATCHED_OUTPUT_PATH)

    # =====================================================
    # 7) station_key 추가된 혼잡도 데이터 저장
    # =====================================================

    congestion_df.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print("=" * 60)
    print("5. station_key 추가된 혼잡도 데이터 저장 완료")
    print("=" * 60)
    print("저장 경로:", OUTPUT_PATH)
    print("최종 크기:", congestion_df.shape)
    print()

    # =====================================================
    # 8) 호선별 매칭 결과
    # =====================================================

    print("=" * 60)
    print("6. 호선별 매칭 결과")
    print("=" * 60)

    line_match_summary = congestion_station_keys.groupby("line")["is_station_matched"].agg(
        total="count",
        matched="sum"
    )

    line_match_summary["unmatched"] = (
        line_match_summary["total"] - line_match_summary["matched"]
    )

    line_match_summary["match_rate"] = (
        line_match_summary["matched"] / line_match_summary["total"] * 100
    ).round(2)

    print(line_match_summary)


# =========================================================
# 5. 실행
# =========================================================

if __name__ == "__main__":
    validate_match()
