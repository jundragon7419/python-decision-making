"""
airkorea_daily.parquet에서 지역(시/도) x 오염물질별로 나눈 32개 parquet 파일을 생성한다.

- PM10: 17개 시/도 전부 (전남, 경북 포함 - PM10은 결측 문제 없음)
- PM2.5: 15개 시/도 (전남, 경북 제외 - 2018년 기준 미달)
- 지역x오염물질마다 유효 시작점(PM10_START/PM25_START) 이후 데이터만 사용
- 해당 오염물질이 NaN인 행은 삭제 (대체 없이 제외, 기존 전처리 방침과 동일)
- 출력: data/processed/processed_by_region/{지역}_{pm10|pm25}.parquet (32개)

사용법:
    python build_regional_parquet.py
"""
import os
import sys
from pathlib import Path

import pandas as pd

# 이 스크립트(src/build_regional_parquet.py) 위치 기준으로 프로젝트 루트를 찾고,
# processed_by_region 폴더를 모듈 검색 경로에 추가한다.
# (실행 위치가 어디든 - 프로젝트 루트든 src든 - 항상 동일하게 동작하도록)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "data" / "processed"))

from processed_by_region import PM10_START, PM25_START # type: ignore 경로 잘 찾아감

INPUT_PATH = PROJECT_ROOT / "data" / "processed" / "airkorea_daily.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "processed_by_region"


def build_region_pollutant_file(daily: pd.DataFrame, region: str, pollutant: str, start_ym: str) -> pd.DataFrame:
    """지역 x 오염물질 하나에 대해, 시작점 이후 + 결측 제외된 데이터를 만든다."""
    start_date = pd.Timestamp(f"{start_ym}-01")
    sub = daily[(daily["sido"] == region) & (daily["date"] >= start_date)]
    sub = sub[["station_code", "station_name", "date", pollutant]].dropna(subset=[pollutant])
    return sub.reset_index(drop=True)


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    daily = pd.read_parquet(INPUT_PATH)
    daily = daily[daily["network"] == "도시대기"].copy()
    daily["date"] = pd.to_datetime(daily["date"])

    total_files = 0
    for pollutant, starts in [("pm10", PM10_START), ("pm25", PM25_START)]:
        for region, start_ym in starts.items():
            sub = build_region_pollutant_file(daily, region, pollutant, start_ym)
            out_path = OUTPUT_DIR / f"{region}_{pollutant}.parquet"
            sub.to_parquet(out_path, index=False)
            print(f"{region}_{pollutant}: {len(sub)}행 (시작 {start_ym}) -> {out_path}")
            total_files += 1

    print(f"\n총 {total_files}개 파일 생성 완료")


if __name__ == "__main__":
    main()