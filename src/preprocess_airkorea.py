"""
에어코리아 xlsx 전처리: 구조 확인 -> 정규화 -> 일평균 집계 -> CSV 저장.

[1부] check_file(): 파일별 dtype/결측치 확인 (완료된 단계, 필요 시 개별 실행)
[2부] 정규화~저장: 확인 결과를 바탕으로 작성된 본 파이프라인
"""
import glob
import os

import pandas as pd

file_paths = [
    "data/raw/2015-2018.xlsx",
    "data/raw/2019.xlsx",
    "data/raw/2020.xlsx",
    "data/raw/2021.xlsx",
    "data/raw/2022.xlsx",
    "data/raw/2023.xlsx",
    "data/raw/2024.xlsx",
]

# 망별 측정소 리스트(.xls, 5개: 교외대기/국가배경/도로변대기/도시대기/항만).
# 측정 데이터(.xlsx)와 확장자가 달라 glob 패턴이 겹치지 않는다.
STATION_LIST_GLOB = "data/raw/*.xls"
NETWORK_NAMES = ["교외대기", "국가배경", "도로변대기", "도시대기", "항만"]
INTERMEDIATE_PATH = "data/processed/airkorea_daily_nojoin_2.parquet"
OUTPUT_PATH = "data/processed/airkorea_daily_2.parquet"

# 컬럼명 표준화: 연도별로 다른 표기를 하나로 통일한다.
COLUMN_MAP: dict[str, str] = {
    "지역": "region",
    "측정소코드": "station_code",
    "측정소명": "station_name",
    "측정일시": "datetime_raw",
    "PM10": "pm10",
    "PM25": "pm25",
    "미세먼지(PM10)": "pm10",
    "초미세먼지(PM25)": "pm25",
}
KEEP_COLUMNS = ["region", "station_code", "station_name", "datetime_raw", "pm10", "pm25"]
MIN_HOURS_PER_DAY = 18  # 하루 24시간 중 최소 관측 시간 (75%). 미만이면 일평균 무효 처리.


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명을 표준명으로 통일하고 필요한 컬럼만 남긴다. pm10/pm25는 float으로 캐스팅."""
    df = df.rename(columns=COLUMN_MAP)[KEEP_COLUMNS]
    df["pm10"] = df["pm10"].astype(float)
    df["pm25"] = df["pm25"].astype(float)
    return df


def parse_date(datetime_raw: pd.Series) -> pd.Series:
    """측정일시(int YYYYMMDDHH 또는 str YYYY-MM-DD-HH)에서 날짜(date)를 추출한다.

    일평균 집계가 목적이므로 시(hour)는 버리고 날짜만 취한다.
    24시 표기도 원본에 기록된 날짜 그대로 귀속시킨다 (해당 일의 마지막 관측이므로).
    """
    s = datetime_raw.astype(str).str.replace("-", "", regex=False)
    return pd.to_datetime(s.str[:8], format="%Y%m%d").dt.date


def load_file(path: str) -> pd.DataFrame:
    """파일 하나(모든 시트)를 읽어 표준 스키마 DataFrame으로 반환한다."""
    sheet_dict = pd.read_excel(path, sheet_name=None, engine="calamine")
    df = pd.concat(sheet_dict.values(), ignore_index=True)
    df = normalize_columns(df)
    df["date"] = parse_date(df["datetime_raw"])
    return df.drop(columns="datetime_raw")


def aggregate_daily(df: pd.DataFrame) -> pd.DataFrame:
    """측정소x일 단위 일평균을 낸다.

    결측치는 mean 계산에서 자동 제외된다. 오염물질별 유효 관측 시간이
    MIN_HOURS_PER_DAY 미만인 날은 해당 오염물질 값을 무효화(NaN)하고,
    pm10/pm25가 모두 NaN이 된 행은 삭제한다. 무효화 규모는 출력으로 보고한다.
    """
    grouped = df.groupby(["station_code", "station_name", "region", "date"]).agg(
        pm10=("pm10", "mean"),
        pm25=("pm25", "mean"),
        pm10_n=("pm10", "count"),
        pm25_n=("pm25", "count"),
    ).reset_index()

    total = len(grouped)
    pm10_invalid = (grouped["pm10_n"] > 0) & (grouped["pm10_n"] < MIN_HOURS_PER_DAY)
    pm25_invalid = (grouped["pm25_n"] > 0) & (grouped["pm25_n"] < MIN_HOURS_PER_DAY)
    print(
        f"  75% 규칙 무효화: pm10 {pm10_invalid.sum()}건 ({pm10_invalid.mean()*100:.2f}%), "
        f"pm25 {pm25_invalid.sum()}건 ({pm25_invalid.mean()*100:.2f}%) / 전체 {total}건"
    )

    grouped.loc[pm10_invalid, "pm10"] = pd.NA
    grouped.loc[pm25_invalid, "pm25"] = pd.NA
    grouped = grouped.drop(columns=["pm10_n", "pm25_n"])

    # 두 물질 모두 값이 없는 행(무효화 또는 원천 결측)은 분석에 기여할 수 없어 삭제.
    before_drop = len(grouped)
    grouped = grouped.dropna(subset=["pm10", "pm25"], how="all")
    print(f"  양쪽 모두 NaN 행 삭제: {before_drop - len(grouped)}건 -> {len(grouped)}건 유지")
    return grouped


def load_station_info() -> pd.DataFrame:
    """망별 측정소 리스트 5개를 합쳐 측정소명 -> (망, 설치년도) 매핑을 만든다.

    망 이름은 파일명에 포함된 키워드로 판별한다.
    측정소명이 망 간에 중복되면 join 시 행이 불어나므로, 중복을 발견하면
    경고를 출력하고 첫 번째 것만 남긴다 (발생 시 원인 확인 필요).
    """
    parts: list[pd.DataFrame] = []
    for path in glob.glob(STATION_LIST_GLOB):
        network = next((n for n in NETWORK_NAMES if n in path), None)
        if network is None:
            print(f"경고: 망 이름을 판별할 수 없어 건너뜀 -> {path}")
            continue
        station = pd.read_excel(path, sheet_name="Sheet1", header=3)
        station.columns = station.columns.str.strip()
        station = station[["측정소명", "설치년도"]].rename(
            columns={"측정소명": "station_name", "설치년도": "install_year"}
        )
        station["network"] = network
        parts.append(station)
        print(f"측정소 리스트 로드: {network} {len(station)}곳 ({path})")

    merged = pd.concat(parts, ignore_index=True)
    dup = merged[merged.duplicated("station_name", keep=False)]
    if len(dup) > 0:
        print(f"경고: 망 간 측정소명 중복 {dup['station_name'].nunique()}건 (첫 번째만 유지):")
        print(dup.sort_values("station_name"))
        merged = merged.drop_duplicates("station_name", keep="first")
    return merged


def build_daily_intermediate() -> pd.DataFrame:
    """[1단계] 전체 파일을 순회해 일평균 집계 후 중간 CSV로 저장한다.

    가장 오래 걸리는 단계이므로, 이후 단계(join)에서 에러가 나도
    처음부터 다시 하지 않도록 결과를 즉시 저장한다.
    중간 CSV가 이미 있으면 재계산 없이 그것을 읽어 반환한다.
    """
    if os.path.exists(INTERMEDIATE_PATH):
        print(f"중간 파일 발견, 집계 생략: {INTERMEDIATE_PATH}")
        return pd.read_parquet(INTERMEDIATE_PATH)

    daily_parts: list[pd.DataFrame] = []
    for path in file_paths:
        print(f"처리 중: {path}")
        daily_parts.append(aggregate_daily(load_file(path)))

    daily = pd.concat(daily_parts, ignore_index=True)
    daily.to_parquet(INTERMEDIATE_PATH, index=False)
    print(f"중간 저장 완료: {len(daily)}행 -> {INTERMEDIATE_PATH}")
    return daily


def join_station_info(daily: pd.DataFrame) -> pd.DataFrame:
    """[2단계] 망/설치년도 join + 시/도 컬럼 추가."""
    station = load_station_info()
    daily = daily.merge(station, on="station_name", how="left")

    # join 매칭률 확인 (폐쇄/개명 측정소는 리스트에 없어 NaN이 될 수 있음)
    unmatched = daily.loc[daily["network"].isna(), "station_name"].nunique()
    total = daily["station_name"].nunique()
    print(f"망/설치년도 join: 전체 측정소 {total}곳 중 미매칭 {unmatched}곳")
    print("망별 측정소 수:")
    print(daily.groupby("network")["station_name"].nunique())

    # 시/도 컬럼 추가 (region 예: "서울 중구" -> "서울"). 대안(17개 시/도) 분석용.
    daily["sido"] = daily["region"].str.split().str[0]
    return daily


daily = join_station_info(build_daily_intermediate())
daily.to_parquet(OUTPUT_PATH, index=False)
print(f"저장 완료: {len(daily)}행 -> {OUTPUT_PATH}")
print(f"날짜 범위: {daily['date'].min()} ~ {daily['date'].max()}")