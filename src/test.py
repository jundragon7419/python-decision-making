"""
processed_by_region의 32개 parquet 파일에 결측치가 남아있는지 검증한다.

검사 항목:
- 오염물질 컬럼(pm10 또는 pm25): 전처리에서 dropna 대상이었으므로 0건이어야 함
- station_code, station_name, date: 원천적으로 결측이 없어야 하는 컬럼

사용법:
    python test_regional_parquet.py
"""
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "processed" / "processed_by_region"

NON_POLLUTANT_COLS = ["station_code", "station_name", "date"]


def check_file(path: Path) -> tuple[bool, str]:
    """파일 하나를 검사한다. (통과 여부, 메시지)를 반환한다."""
    df = pd.read_parquet(path)

    # 파일명에서 오염물질 추출 (예: 서울_pm25.parquet -> pm25)
    pollutant = path.stem.split("_")[-1]
    if pollutant not in ("pm10", "pm25"):
        return False, f"파일명에서 오염물질을 판별할 수 없음: {path.name}"

    problems = []

    pollutant_missing = df[pollutant].isna().sum()
    if pollutant_missing > 0:
        problems.append(f"{pollutant} 결측 {pollutant_missing}건")

    for col in NON_POLLUTANT_COLS:
        if col not in df.columns:
            problems.append(f"컬럼 없음: {col}")
            continue
        n_missing = df[col].isna().sum()
        if n_missing > 0:
            problems.append(f"{col} 결측 {n_missing}건")

    if len(df) == 0:
        problems.append("빈 파일 (행 0개)")

    if problems:
        return False, f"{path.name}: " + ", ".join(problems)
    return True, f"{path.name}: 이상 없음 ({len(df)}행)"


def main() -> None:
    files = sorted(DATA_DIR.glob("*.parquet"))
    print(f"검사 대상: {len(files)}개 파일\n")

    results = [check_file(f) for f in files]

    for ok, msg in results:
        prefix = "OK  " if ok else "FAIL"
        print(f"[{prefix}] {msg}")

    n_pass = sum(ok for ok, _ in results)
    n_fail = len(results) - n_pass
    print(f"\n통과: {n_pass}개 / 실패: {n_fail}개 / 전체: {len(results)}개")

    if len(files) != 32:
        print(f"주의: 예상 파일 수(32개)와 다릅니다. 실제: {len(files)}개")


if __name__ == "__main__":
    main()