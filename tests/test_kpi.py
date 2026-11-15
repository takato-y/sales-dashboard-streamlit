"""指標・月次推移・絞り込み（FN-003〜FN-005）のテスト。

期待値は pandas を使わず、CSV を標準ライブラリの csv で読んで素朴に計算した値と突き合わせる。
"""

import csv
from collections import defaultdict

import pandas as pd
import pytest

from sales_dashboard import generator, kpi, loader
from sales_dashboard import schema as s
from sales_dashboard.filters import FilterCondition, apply_filters, month_range, options
from tests.helpers import row, to_csv_bytes

P = lambda x: pd.Period(x, freq="M")  # noqa: E731


@pytest.fixture(scope="module")
def two_years(tmp_path_factory):
    """2 年分の架空データを CSV に書き、アプリと同じ経路で読み込む。"""
    path = tmp_path_factory.mktemp("data") / "sales.csv"
    generator.generate_sales(seed=11, months=24, lines_per_month=600).to_csv(path, index=False)
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return loader.load_paths([str(path)]), rows


def plain_monthly(rows, staff=None, category=None):
    """標準ライブラリだけで、月ごとの売上・粗利（整数）を計算する。"""
    sales, profit = defaultdict(int), defaultdict(int)
    for r in rows:
        if staff and r["担当者"] != staff:
            continue
        if category and r["商品カテゴリ"] != category:
            continue
        m = r["売上日"][:7]
        q, p, c = int(r["数量"]), int(r["単価"]), int(r["原価単価"])
        sales[m] += q * p
        profit[m] += q * (p - c)
    return sales, profit


def test_tc020_kpis_match_plain_python(two_years):
    result, rows = two_years
    cond = FilterCondition(P("2025-04"), P("2025-09"), staff=("佐藤",), categories=("食品",))
    k = kpi.compute_kpis(result.data, cond)
    sales, profit = plain_monthly(rows, staff="佐藤", category="食品")
    months = [f"2025-{m:02d}" for m in range(4, 10)]
    exp_sales = sum(sales[m] for m in months)
    exp_profit = sum(profit[m] for m in months)
    assert k.sales == exp_sales
    assert k.profit == exp_profit
    assert k.margin == pytest.approx(exp_profit / exp_sales)
    assert k.target_month == P("2025-09")
    assert k.month_sales == sales["2025-09"]
    assert k.mom == pytest.approx(sales["2025-09"] / sales["2025-08"])
    assert k.yoy == pytest.approx(sales["2025-09"] / sales["2024-09"])
    exp_rows = sum(1 for r in rows if r["担当者"] == "佐藤" and r["商品カテゴリ"] == "食品"
                   and "2025-04" <= r["売上日"][:7] <= "2025-09")
    assert k.rows == exp_rows


def test_tc021_monthly_trend_matches_plain_python(two_years):
    result, rows = two_years
    cond = FilterCondition(P("2025-01"), P("2025-12"), categories=("飲料",))
    t = kpi.monthly_trend(result.data, cond)
    sales, profit = plain_monthly(rows, category="飲料")
    assert len(t) == 12
    for _, r in t.iterrows():
        m = str(r["年月"])
        prev = f"2024-{m[5:]}"
        assert r["売上"] == sales[m] and r["粗利"] == profit[m]
        assert r["粗利率"] == pytest.approx(profit[m] / sales[m])
        assert r["前年同月売上"] == sales[prev]
        assert r["前年同月比"] == pytest.approx(sales[m] / sales[prev])


def test_tc022_first_year_has_no_yoy(two_years):
    result, _ = two_years
    t = kpi.monthly_trend(result.data, FilterCondition(P("2024-01"), P("2024-03")))
    assert t["前年同月売上"].isna().all() and t["前年同月比"].isna().all()
    k = kpi.compute_kpis(result.data, FilterCondition(P("2024-01"), P("2024-01")))
    assert k.yoy is None and k.mom is None  # 前年・前月のデータがない


def test_tc023_zero_base_and_missing_month():
    # 1 月は担当 B だけ、2 月は担当 A だけ。担当 A で絞ると 1 月は「データはあるが 0」
    rows = [row(slip="1", day="2025-01-06", staff="B", qty=1, price=100),
            row(slip="2", day="2025-02-03", staff="A", qty=2, price=100),
            row(slip="3", day="2025-04-01", staff="A", qty=1, price=100)]
    data = loader.load_files([("a.csv", to_csv_bytes(rows))]).data
    k = kpi.compute_kpis(data, FilterCondition(P("2025-02"), P("2025-02"), staff=("A",)))
    assert k.prev_month_sales == 0 and k.mom is None  # 分母 0 は算出しない
    t = kpi.monthly_trend(data, FilterCondition(P("2025-01"), P("2025-04"), staff=("A",)))
    assert list(t["売上"].fillna(-1)) == [0, 200, -1, 100]  # 3 月はデータ自体がない → 空欄
    assert pd.isna(t.loc[0, "粗利率"])


def test_tc024_margin_with_zero_or_negative_sales():
    assert kpi.margin(10, 0) is None
    assert kpi.margin(-10, -100) is None
    assert kpi.margin(25, 100) == 0.25


def test_tc025_filters_and_options(two_years):
    result, rows = two_years
    cond = FilterCondition(P("2024-12"), P("2025-01"), regions=("関東", "九州"))
    got = apply_filters(result.data, cond)
    exp = [r for r in rows if r["地域"] in ("関東", "九州") and r["売上日"][:7] in ("2024-12", "2025-01")]
    assert len(got) == len(exp)
    assert options(result.data, s.COL_CATEGORY) == sorted({r["商品カテゴリ"] for r in rows})
    months = month_range(result.data)
    assert months[0] == P("2024-01") and months[-1] == P("2025-12") and len(months) == 24


def test_tc026_empty_filter_result():
    data = loader.load_files([("a.csv", to_csv_bytes([row()]))]).data
    k = kpi.compute_kpis(data, FilterCondition(staff=("存在しない担当",)))
    assert k.sales == 0 and k.margin is None and k.rows == 0
