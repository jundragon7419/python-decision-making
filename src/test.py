import pandas as pd
for name in ["airkorea_daily", "airkorea_daily_nojoin"]:
    df = pd.read_csv(f"data/processed/{name}.csv")
    df.to_parquet(f"data/processed/{name}.parquet", index=False)
    print(f"{name}: 변환 완료")