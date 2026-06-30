from pathlib import Path
from datetime import datetime
import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================

BASE_DIR = Path.cwd()

CONGESTION_PATH = BASE_DIR / "data" / "processed" / "congestion_long_with_station_key.csv"


# =========================================================
# 2. 시간 처리 함수
# =========================================================

def time_to_index(time_text: str) -> int:
    """
    '08:42' 같은 시간을 혼잡도 데이터의 30분 단위 time_index로 변환한다.

    예:
    08:42 -> 08:30 -> 510
    18:10 -> 18:00 -> 1080
    00:20 -> 00:00 -> 1440
    00:40 -> 00:30 -> 1470
    """
    hour, minute = map(int, time_text.split(":"))

    # 30분 단위로 내림 처리
    minute = 30 if minute >= 30 else 0

    # 지하철 운행 흐름상 00시대는 다음날 시간으로 처리
    service_hour = hour + 24 if hour < 5 else hour

    return service_hour * 60 + minute


def time_index_to_slot(time_index: int) -> str:
    """
    time_index를 사람이 보기 쉬운 시간대 문자열로 변환한다.

    예:
    510 -> 8시30분
    1470 -> 00시30분
    """
    hour = time_index // 60
    minute = time_index % 60

    if hour >= 24:
        hour -= 24

    return f"{hour:02d}시{minute:02d}분"


# =========================================================
# 3. 혼잡도 데이터 로드
# =========================================================

def load_congestion_data() -> pd.DataFrame:
    if not CONGESTION_PATH.exists():
        raise FileNotFoundError(
            f"혼잡도 전처리 파일을 찾을 수 없습니다.\n"
            f"찾는 경로: {CONGESTION_PATH}\n"
            f"congestion_long_with_station_key.csv 파일이 있는지 확인하세요."
        )

    df = pd.read_csv(CONGESTION_PATH, encoding="utf-8-sig")

    required_cols = [
        "day_type",
        "line",
        "station_name",
        "direction",
        "time_slot",
        "time_index",
        "congestion",
        "official_level",
        "service_level",
        "congestion_level",
        "station_key",
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing_cols}\n"
            f"현재 컬럼: {df.columns.tolist()}"
        )

    return df


# =========================================================
# 4. 혼잡도 조회 함수
# =========================================================

def get_congestion_by_station_key(
    df: pd.DataFrame,
    day_type: str,
    line: str,
    station_key: str,
    direction: str,
    time_text: str,
) -> dict | None:
    """
    요일, 호선, 역 key, 방향, 시간을 기준으로 혼잡도 데이터를 조회한다.

    Parameters
    ----------
    df : 혼잡도 데이터프레임
    day_type : 평일 / 토요일 / 일요일
    line : 1호선, 2호선 ...
    station_key : 2호선_강남 같은 key
    direction : 상선 / 하선 / 내선 / 외선
    time_text : '08:42' 같은 현재 또는 도착 예정 시간

    Returns
    -------
    dict 또는 None
    """
    target_time_index = time_to_index(time_text)

    result = df[
        (df["day_type"] == day_type) &
        (df["line"] == line) &
        (df["station_key"] == station_key) &
        (df["direction"] == direction) &
        (df["time_index"] == target_time_index)
    ]

    if result.empty:
        return None

    row = result.iloc[0]

    return {
        "day_type": row["day_type"],
        "line": row["line"],
        "station_name": row["station_name"],
        "station_key": row["station_key"],
        "direction": row["direction"],
        "input_time": time_text,
        "matched_time_slot": row["time_slot"],
        "matched_time_index": int(row["time_index"]),
        "congestion": float(row["congestion"]),
        "official_level": row["official_level"],
        "service_level": row["service_level"],
        "congestion_level": row["congestion_level"],
    }


# =========================================================
# 5. 테스트 실행
# =========================================================

if __name__ == "__main__":
    congestion_df = load_congestion_data()

    print("=" * 60)
    print("혼잡도 데이터 로드 완료")
    print("=" * 60)
    print("데이터 크기:", congestion_df.shape)
    print("컬럼:", congestion_df.columns.tolist())
    print()

    # 테스트 1: 2호선 강남 외선 평일 08:42
    test_result = get_congestion_by_station_key(
        df=congestion_df,
        day_type="평일",
        line="2호선",
        station_key="2호선_강남",
        direction="외선",
        time_text="08:42",
    )

    print("=" * 60)
    print("테스트 결과 1")
    print("=" * 60)

    if test_result is None:
        print("조회 결과 없음")
    else:
        for key, value in test_result.items():
            print(f"{key}: {value}")

    print()

    # 테스트 2: 2호선 강남 내선 평일 18:12
    test_result = get_congestion_by_station_key(
        df=congestion_df,
        day_type="평일",
        line="2호선",
        station_key="2호선_강남",
        direction="내선",
        time_text="18:12",
    )

    print("=" * 60)
    print("테스트 결과 2")
    print("=" * 60)

    if test_result is None:
        print("조회 결과 없음")
    else:
        for key, value in test_result.items():
            print(f"{key}: {value}")