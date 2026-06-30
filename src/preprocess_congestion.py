from pathlib import Path
import re

import pandas as pd


# =========================================================
# 1. 파일 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

RAW_PATH = BASE_DIR / "data" / "raw" / "서울교통공사_지하철혼잡도정보_20260331.csv"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OUTPUT_PATH = PROCESSED_DIR / "congestion_long.csv"

print("현재 작업 폴더:", BASE_DIR)
print("CSV 찾는 경로:", RAW_PATH)


# =========================================================
# 2. 시간대 파싱 함수
# =========================================================

def parse_time_slot(time_slot: str) -> tuple[int, int, int]:
    """
    '5시30분', '6시00분', '23시30분', '00시30분' 형식의 시간대 문자열을
    hour, minute, time_index로 변환한다.

    예시:
    5시30분  -> hour=5,  minute=30, time_index=330
    8시00분  -> hour=8,  minute=0,  time_index=480
    23시30분 -> hour=23, minute=30, time_index=1410
    00시30분 -> hour=0,  minute=30, time_index=1470

    00시30분은 지하철 운행 흐름상 23시30분 뒤에 와야 하므로
    time_index 계산에서는 24시30분으로 처리한다.
    """
    time_slot = str(time_slot).strip()

    match = re.match(r"^(\d{1,2})시(\d{2})분$", time_slot)

    if not match:
        raise ValueError(f"시간대 형식이 올바르지 않습니다: {time_slot}")

    hour = int(match.group(1))
    minute = int(match.group(2))

    service_hour = hour + 24 if hour < 5 else hour
    time_index = service_hour * 60 + minute

    return hour, minute, time_index


# =========================================================
# 3. 공식 혼잡도 등급 함수
# =========================================================

def get_official_congestion_level(value: float) -> str:
    """
    공식 혼잡도 기준에 가까운 등급 분류.

    80 이하       -> 여유
    80 초과~130  -> 보통
    130 초과~150 -> 주의
    150 초과~170 -> 혼잡
    170 초과     -> 매우혼잡

    현재 서울교통공사_지하철혼잡도정보_20260331.csv에서는
    150을 넘는 값이 거의 없거나 없을 수 있다.
    """
    if value <= 80:
        return "여유"
    elif value <= 130:
        return "보통"
    elif value <= 150:
        return "주의"
    elif value <= 170:
        return "혼잡"
    else:
        return "매우혼잡"


# =========================================================
# 4. 서비스 화면용 혼잡도 등급 함수
# =========================================================

def get_service_congestion_level(value: float) -> str:
    """
    프로젝트 화면 표시용 혼잡도 등급.

    공식 기준만 사용하면 대부분 '여유' 또는 '보통'으로 표시되기 때문에,
    실제 CSV 분포를 반영한 서비스용 등급을 별도로 사용한다.

    50 이하       -> 여유
    50 초과~70   -> 보통
    70 초과~90   -> 다소혼잡
    90 초과~110  -> 혼잡
    110 초과     -> 매우혼잡
    """
    if value <= 50:
        return "여유"
    elif value <= 70:
        return "보통"
    elif value <= 90:
        return "다소혼잡"
    elif value <= 110:
        return "혼잡"
    else:
        return "매우혼잡"


# =========================================================
# 5. 메인 전처리 함수
# =========================================================

def preprocess_congestion_data() -> pd.DataFrame:
    # 저장 폴더 생성
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # 원본 CSV 로드
    df = pd.read_csv(RAW_PATH, encoding="cp949")

    print("=" * 60)
    print("1. 원본 데이터 로드 완료")
    print("=" * 60)
    print("원본 경로:", RAW_PATH)
    print("원본 크기:", df.shape)
    print("원본 컬럼:")
    print(df.columns.tolist())
    print()

    # =====================================================
    # 1) ID 컬럼과 시간대 컬럼 분리
    # =====================================================

    id_cols = ["요일구분", "호선", "역번호", "출발역", "상하구분"]

    missing_id_cols = [col for col in id_cols if col not in df.columns]
    if missing_id_cols:
        raise ValueError(f"필수 ID 컬럼이 없습니다: {missing_id_cols}")

    time_cols = [col for col in df.columns if col not in id_cols]

    print("=" * 60)
    print("2. ID 컬럼 / 시간대 컬럼 분리")
    print("=" * 60)
    print("ID 컬럼:", id_cols)
    print("시간대 컬럼 개수:", len(time_cols))
    print("시간대 컬럼 앞부분:", time_cols[:5])
    print("시간대 컬럼 뒷부분:", time_cols[-5:])
    print()

    # =====================================================
    # 2) pandas.melt로 wide -> long 변환
    # =====================================================

    df_long = pd.melt(
        df,
        id_vars=id_cols,
        value_vars=time_cols,
        var_name="time_slot",
        value_name="congestion"
    )

    print("=" * 60)
    print("3. wide -> long 변환 완료")
    print("=" * 60)
    print("변환 후 크기:", df_long.shape)
    print(df_long.head())
    print()

    # =====================================================
    # 3) 한글 컬럼명을 영문 컬럼명으로 변경
    # =====================================================

    df_long = df_long.rename(columns={
        "요일구분": "day_type",
        "호선": "line",
        "역번호": "station_id",
        "출발역": "station_name",
        "상하구분": "direction"
    })

    # =====================================================
    # 4) 혼잡도 값을 float로 변환
    # =====================================================

    df_long["congestion"] = pd.to_numeric(df_long["congestion"], errors="coerce")

    missing_congestion_count = df_long["congestion"].isna().sum()

    print("=" * 60)
    print("4. 혼잡도 숫자형 변환")
    print("=" * 60)
    print("혼잡도 변환 실패 개수:", missing_congestion_count)
    print()

    if missing_congestion_count > 0:
        print("혼잡도 변환 실패 행 예시:")
        print(df_long[df_long["congestion"].isna()].head())
        print()

    # =====================================================
    # 5) time_slot에서 hour, minute, time_index 생성
    # =====================================================

    parsed_times = df_long["time_slot"].apply(parse_time_slot)

    df_long["hour"] = parsed_times.apply(lambda x: x[0])
    df_long["minute"] = parsed_times.apply(lambda x: x[1])
    df_long["time_index"] = parsed_times.apply(lambda x: x[2])

    # =====================================================
    # 6) 혼잡도 등급 컬럼 생성
    # =====================================================

    df_long["official_level"] = df_long["congestion"].apply(get_official_congestion_level)
    df_long["service_level"] = df_long["congestion"].apply(get_service_congestion_level)

    # 앱에서 기본으로 사용할 등급
    df_long["congestion_level"] = df_long["service_level"]

    # =====================================================
    # 7) 컬럼 순서 정리
    # =====================================================

    df_long = df_long[
        [
            "day_type",
            "line",
            "station_id",
            "station_name",
            "direction",
            "time_slot",
            "hour",
            "minute",
            "time_index",
            "congestion",
            "official_level",
            "service_level",
            "congestion_level",
        ]
    ]

    # =====================================================
    # 8) 정렬
    # =====================================================

    df_long = df_long.sort_values(
        by=[
            "day_type",
            "line",
            "station_id",
            "direction",
            "time_index"
        ]
    ).reset_index(drop=True)

    # =====================================================
    # 9) 저장
    # =====================================================

    df_long.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("=" * 60)
    print("5. 전처리 완료")
    print("=" * 60)
    print("저장 경로:", OUTPUT_PATH)
    print("최종 크기:", df_long.shape)
    print()
    print("최종 컬럼:")
    print(df_long.columns.tolist())
    print()
    print("최종 데이터 예시:")
    print(df_long.head(10))
    print()

    return df_long


# =========================================================
# 6. 데이터 검증 함수
# =========================================================

def validate_processed_data(df_long: pd.DataFrame) -> None:
    print("=" * 60)
    print("6. 전체 혼잡도 분포 확인")
    print("=" * 60)

    print(
        df_long["congestion"].describe(
            percentiles=[0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        )
    )
    print()

    print("전체 공식 등급 분포:")
    print(df_long["official_level"].value_counts())
    print()

    print("전체 서비스 등급 분포:")
    print(df_long["service_level"].value_counts())
    print()

    # 출퇴근 시간 컬럼은 저장하지 않고, 검증할 때만 임시로 사용
    peak_slots = {
        "7시00분", "7시30분", "8시00분", "8시30분", "9시00분",
        "17시30분", "18시00분", "18시30분", "19시00분", "19시30분"
    }

    peak_df = df_long[
        (df_long["day_type"] == "평일") &
        (df_long["time_slot"].isin(peak_slots))
    ]

    print("=" * 60)
    print("7. 평일 출퇴근 시간대 혼잡도 분포 확인")
    print("=" * 60)
    print("평일 출퇴근 데이터 크기:", peak_df.shape)
    print()

    print(
        peak_df["congestion"].describe(
            percentiles=[0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        )
    )
    print()

    print("평일 출퇴근 공식 등급 분포:")
    print(peak_df["official_level"].value_counts())
    print()

    print("평일 출퇴근 서비스 등급 분포:")
    print(peak_df["service_level"].value_counts())
    print()

    print("=" * 60)
    print("8. 평일 출퇴근 시간대 기준 초과값 개수")
    print("=" * 60)

    thresholds = [50, 70, 80, 90, 100, 110, 120, 130, 150]

    for threshold in thresholds:
        count = (peak_df["congestion"] > threshold).sum()
        ratio = count / len(peak_df) * 100 if len(peak_df) > 0 else 0
        print(f"{threshold} 초과: {count}개 / {ratio:.2f}%")

    print()

    print("=" * 60)
    print("9. 노선별 혼잡도 요약")
    print("=" * 60)

    line_stats = df_long.groupby("line")["congestion"].describe(
        percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]
    )

    print(line_stats)
    print()

    print("=" * 60)
    print("10. 혼잡도 상위 20개")
    print("=" * 60)

    top20 = df_long.sort_values("congestion", ascending=False).head(20)

    print(
        top20[
            [
                "day_type",
                "line",
                "station_name",
                "direction",
                "time_slot",
                "congestion",
                "official_level",
                "service_level"
            ]
        ]
    )
    print()


# =========================================================
# 7. 실행
# =========================================================

if __name__ == "__main__":
    processed_df = preprocess_congestion_data()
    validate_processed_data(processed_df)