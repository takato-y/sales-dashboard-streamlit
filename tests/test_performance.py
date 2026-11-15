"""性能（REQ-101）：10 万行を読み込み・検証・集計まで 10 秒以内。

計測値は -s を付けて実行すると表示される（python -m pytest -m perf -s）。
"""

import time

import pandas as pd
import pytest

from sales_dashboard import db, export, generator, loader
from sales_dashboard.filters import FilterCondition

ROWS = 100_000
LIMIT_SECONDS = 10.0


@pytest.mark.perf
def test_tc070_100k_rows_within_10_seconds():
    df = generator.generate_sales(seed=99, months=24, lines_per_month=4300).head(ROWS)
    assert len(df) == ROWS
    content = df.to_csv(index=False).encode("utf-8")
    timings = {}

    t0 = time.perf_counter()
    result = loader.load_files([("sales_100k.csv", content)])
    timings["読み込み・検証"] = time.perf_counter() - t0

    t = time.perf_counter()
    d = db.SalesDB()
    d.load(result)
    timings["SQLite への取込"] = time.perf_counter() - t

    t = time.perf_counter()
    cond = FilterCondition(pd.Period("2025-01", "M"), pd.Period("2025-12", "M"))
    d.set_condition(cond)
    k = d.kpis()
    report = export.ReportData(cond, k, d.monthly_trend(), d.abc("得意先"), d.abc("商品"),
                               d.breakdown("地域"), d.breakdown("担当者"), d.breakdown("商品カテゴリ"))
    timings["集計（ビュー 8 本）"] = time.perf_counter() - t
    total = time.perf_counter() - t0

    t = time.perf_counter()
    export.build_excel(report)
    timings["Excel 出力（参考）"] = time.perf_counter() - t

    print(f"\n[性能] {ROWS:,} 行（受け付け {len(result.data):,} 行）")
    for name, sec in timings.items():
        print(f"  {name}: {sec:.2f} 秒")
    print(f"  合計（読み込み〜集計）: {total:.2f} 秒（基準 {LIMIT_SECONDS:.0f} 秒以内）")
    assert len(result.data) == ROWS and k.rows > 0
    assert total < LIMIT_SECONDS


@pytest.mark.perf
def test_tc071_100k_rows_excel_reference(tmp_path):
    """Excel（.xlsx）で 10 万行を読む時間の参考値。基準は CSV で判定し、ここでは時間を記録するだけ。"""
    df = generator.generate_sales(seed=99, months=24, lines_per_month=4300).head(ROWS)
    path = tmp_path / "sales_100k.xlsx"
    df.to_excel(path, index=False)
    t = time.perf_counter()
    result = loader.load_paths([str(path)])
    sec = time.perf_counter() - t
    print(f"\n[性能・参考] Excel {ROWS:,} 行の読み込み・検証: {sec:.2f} 秒")
    assert len(result.data) == ROWS
