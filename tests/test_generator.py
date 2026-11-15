"""架空データ生成（FN-010）のテスト。"""

import pandas as pd

from sales_dashboard import generator
from sales_dashboard import schema as s


def test_tc090_same_seed_gives_same_rows():
    a = generator.generate_sales(seed=1, months=2, lines_per_month=50)
    b = generator.generate_sales(seed=1, months=2, lines_per_month=50)
    pd.testing.assert_frame_equal(a, b)


def test_tc091_columns_and_period():
    df = generator.generate_sales(seed=3, start="2024-01", months=24, lines_per_month=200)
    assert list(df.columns) == s.REQUIRED_COLUMNS
    months = sorted(df[s.COL_DATE].str.slice(0, 7).unique())
    assert months[0] == "2024-01" and months[-1] == "2025-12" and len(months) == 24
    # 土日・年始は含まない
    dates = pd.to_datetime(df[s.COL_DATE])
    assert (dates.dt.day_of_week < 5).all()
    assert not ((dates.dt.month == 1) & (dates.dt.day <= 3)).any()


def test_tc092_seasonality_december_above_august():
    df = generator.generate_sales(seed=5, months=24, lines_per_month=400)
    df["amount"] = df[s.COL_QTY] * df[s.COL_PRICE]
    by_month = df.groupby(df[s.COL_DATE].str.slice(5, 7))["amount"].sum()
    assert by_month["12"] > by_month["08"] * 1.2


def test_tc093_slip_line_key_is_unique():
    df = generator.generate_sales(seed=9, months=3, lines_per_month=300)
    assert not df.duplicated([s.COL_SLIP, s.COL_LINE]).any()
