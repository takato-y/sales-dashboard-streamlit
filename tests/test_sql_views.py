"""SQL 集計層（FN-003〜FN-007・FN-012）のテスト。

ビューの結果を、pandas も SQL も使わず標準ライブラリの csv で CSV を読んで素朴に計算した期待値と
突き合わせる（同じ計算方法で検算しないため）。
"""

import csv
import sqlite3
from collections import defaultdict

import pandas as pd
import pytest

from sales_dashboard import db, generator, loader
from sales_dashboard.filters import FilterCondition
from tests.helpers import row, to_csv_bytes

P = lambda x: pd.Period(x, freq="M")  # noqa: E731


def make_db(rows) -> db.SalesDB:
    d = db.SalesDB()
    d.load(loader.load_files([("a.csv", to_csv_bytes(rows))]))
    return d


@pytest.fixture(scope="module")
def two_years(tmp_path_factory):
    """2 年分の架空データを CSV に書き、アプリと同じ経路（loader → SQLite）で読み込む。"""
    path = tmp_path_factory.mktemp("data") / "sales.csv"
    generator.generate_sales(seed=11, months=24, lines_per_month=600).to_csv(path, index=False)
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    d = db.SalesDB()
    d.load(loader.load_paths([str(path)]))
    return d, rows


def plain_monthly(rows, staff=None, category=None, region=None):
    """標準ライブラリだけで、月ごとの売上・粗利（整数）を計算する。"""
    sales, profit = defaultdict(int), defaultdict(int)
    for r in rows:
        if (staff and r["担当者"] != staff) or (category and r["商品カテゴリ"] != category) \
                or (region and r["地域"] != region):
            continue
        m = r["売上日"][:7]
        q, p, c = int(r["数量"]), int(r["単価"]), int(r["原価単価"])
        sales[m] += q * p
        profit[m] += q * (p - c)
    return sales, profit


def plain_abc(rows, key, cond_months):
    sales = defaultdict(int)
    for r in rows:
        if r["売上日"][:7] in cond_months:
            sales[r[key]] += int(r["数量"]) * int(r["単価"])
    ordered = sorted(sales.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(sales.values())
    cum, out = 0.0, []
    for code, v in ordered:
        before = cum
        cum += v / total
        out.append((code, v, "A" if before < 0.7 else "B" if before < 0.9 else "C"))
    return out


# ---- FN-012 スキーマの適用

def test_tc040_migrations_are_versioned_and_idempotent():
    d = db.SalesDB()
    versions = [v for v, _ in db.migration_files()]
    assert d.schema_versions() == versions and versions[:2] == [1, 2]
    assert d.migrate() == []  # 2 回目は何も適用しない


def test_tc041_file_database_keeps_versions(tmp_path):
    path = str(tmp_path / "sales.sqlite")
    db.SalesDB(path).conn.close()
    again = db.SalesDB(path)
    assert again.migrate() == [] and again.schema_versions()[:2] == [1, 2]


# ---- FN-012 取込（金額は SQL で計算）

def test_tc045_amounts_and_masters_are_computed_in_sql():
    d = make_db([row(slip="1", qty=3, price=120, cost=80, cname="旧名", day="2025-01-06"),
                 row(slip="2", qty=-2, price=100, cost=70, cname="新名", day="2025-02-03")])
    got = d.query("SELECT slip_no, ym, ym_idx, sales_amount, cost_amount, gross_profit FROM t_sales_line "
                  "ORDER BY slip_no").values.tolist()
    assert got == [["1", "2025-01", 2025 * 12, 360.0, 240.0, 120.0],
                   ["2", "2025-02", 2025 * 12 + 1, -200.0, -140.0, -60.0]]
    assert d.query("SELECT customer_name FROM m_customer").iloc[0, 0] == "新名"  # 最も新しい売上日の名称
    assert d.import_files().values.tolist() == [["a.csv", 2, 0]]


def test_tc046_reload_replaces_all_rows():
    d = make_db([row(slip="1"), row(slip="2")])
    d.load(loader.load_files([("b.csv", to_csv_bytes([row(slip="9")]))]))
    assert d.query("SELECT slip_no FROM t_sales_line").iloc[:, 0].tolist() == ["9"]
    assert d.query("SELECT COUNT(*) FROM stg_sales_line").iloc[0, 0] == 0


def test_tc047_check_constraint_rejects_zero_quantity():
    d = make_db([row()])
    with pytest.raises(sqlite3.IntegrityError):
        d.conn.execute("INSERT INTO t_sales_line SELECT slip_no || 'x', line_no, sales_date, ym, ym_idx, "
                       "customer_code, region, staff, product_code, category, 0, unit_price, unit_cost, "
                       "0, 0, 0, file_id, source_row FROM t_sales_line")


# ---- FN-004・FN-005 指標と月次推移

def test_tc020_kpis_match_plain_python(two_years):
    d, rows = two_years
    d.set_condition(FilterCondition(P("2025-04"), P("2025-09"), staff=("佐藤",), categories=("食品",)))
    k = d.kpis()
    sales, profit = plain_monthly(rows, staff="佐藤", category="食品")
    months = [f"2025-{m:02d}" for m in range(4, 10)]
    exp_sales = sum(sales[m] for m in months)
    exp_profit = sum(profit[m] for m in months)
    assert k.sales == exp_sales and k.profit == exp_profit
    assert k.margin == pytest.approx(exp_profit / exp_sales)
    assert k.target_month == "2025-09" and k.month_sales == sales["2025-09"]
    assert k.mom == pytest.approx(sales["2025-09"] / sales["2025-08"])
    assert k.yoy == pytest.approx(sales["2025-09"] / sales["2024-09"])
    exp_rows = sum(1 for r in rows if r["担当者"] == "佐藤" and r["商品カテゴリ"] == "食品"
                   and "2025-04" <= r["売上日"][:7] <= "2025-09")
    assert k.rows == exp_rows


def test_tc021_monthly_trend_matches_plain_python(two_years):
    d, rows = two_years
    d.set_condition(FilterCondition(P("2025-01"), P("2025-12"), categories=("飲料",)))
    t = d.monthly_trend()
    sales, profit = plain_monthly(rows, category="飲料")
    assert len(t) == 12
    for _, r in t.iterrows():
        m = r["年月"]
        prev = f"2024-{m[5:]}"
        assert r["売上"] == sales[m] and r["粗利"] == profit[m]
        assert r["粗利率"] == pytest.approx(profit[m] / sales[m])
        assert r["前年同月売上"] == sales[prev]
        assert r["前年同月比"] == pytest.approx(sales[m] / sales[prev])


def test_tc022_first_year_has_no_yoy(two_years):
    d, _ = two_years
    d.set_condition(FilterCondition(P("2024-01"), P("2024-03")))
    t = d.monthly_trend()
    assert t["前年同月売上"].isna().all() and t["前年同月比"].isna().all()
    d.set_condition(FilterCondition(P("2024-01"), P("2024-01")))
    k = d.kpis()
    assert k.yoy is None and k.mom is None  # 前年・前月のデータがない


def test_tc023_zero_base_and_missing_month():
    # 1 月は担当 B だけ、2 月・4 月は担当 A だけ、3 月はデータ自体がない
    d = make_db([row(slip="1", day="2025-01-06", staff="B", qty=1, price=100),
                 row(slip="2", day="2025-02-03", staff="A", qty=2, price=100),
                 row(slip="3", day="2025-04-01", staff="A", qty=1, price=100)])
    d.set_condition(FilterCondition(P("2025-02"), P("2025-02"), staff=("A",)))
    k = d.kpis()
    assert k.prev_month_sales == 0 and k.mom is None  # 分母 0 は算出しない
    d.set_condition(FilterCondition(P("2025-01"), P("2025-04"), staff=("A",)))
    t = d.monthly_trend()
    assert list(t["売上"].fillna(-1)) == [0, 200, -1, 100]  # 3 月はデータがない → 空欄
    assert pd.isna(t.loc[0, "粗利率"])
    assert d.months() == ["2025-01", "2025-02", "2025-03", "2025-04"]


def test_tc024_margin_with_zero_or_negative_sales():
    d = make_db([row(slip="1", qty=-1, price=100, cost=70)])
    k = d.kpis()
    assert k.sales == -100 and k.margin is None


def test_tc025_filters_and_options(two_years):
    d, rows = two_years
    d.set_condition(FilterCondition(P("2024-12"), P("2025-01"), regions=("関東", "九州")))
    exp = [r for r in rows if r["地域"] in ("関東", "九州") and r["売上日"][:7] in ("2024-12", "2025-01")]
    assert d.kpis().rows == len(exp)
    assert d.options("商品カテゴリ") == sorted({r["商品カテゴリ"] for r in rows})
    months = d.months()
    assert months[0] == "2024-01" and months[-1] == "2025-12" and len(months) == 24


def test_tc026_empty_filter_result():
    d = make_db([row()])
    d.set_condition(FilterCondition(staff=("存在しない担当",)))
    k = d.kpis()
    assert k.sales == 0 and k.margin is None and k.rows == 0
    assert d.abc("得意先").empty and d.breakdown("地域").empty


def test_tc027_empty_database():
    d = db.SalesDB()
    d.load(loader.load_files([]))
    k = d.kpis()
    assert k.rows == 0 and k.target_month is None and d.months() == []
    assert d.monthly_trend().empty


# ---- FN-006・FN-007 ABC 分析と内訳

def test_tc030_abc_matches_plain_python(two_years):
    d, rows = two_years
    d.set_condition(FilterCondition(P("2025-01"), P("2025-12")))
    months = {f"2025-{m:02d}" for m in range(1, 13)}
    for kind, key in (("得意先", "得意先コード"), ("商品", "商品コード")):
        got = d.abc(kind)
        exp = plain_abc(rows, key, months)
        assert list(got["コード"]) == [e[0] for e in exp]
        assert list(got["売上"]) == [e[1] for e in exp]
        assert list(got["区分"]) == [e[2] for e in exp]
        assert got["累積構成比"].iloc[-1] == pytest.approx(1.0)


def test_tc031_abc_boundary_and_negative():
    # 構成比 約 80%・10%・6%・4%、さらに返品で売上がマイナスの得意先
    d = make_db([row(slip="1", cust="C1", qty=80, price=100), row(slip="2", cust="C2", qty=10, price=100),
                 row(slip="3", cust="C3", qty=6, price=100), row(slip="4", cust="C4", qty=4, price=100),
                 row(slip="5", cust="C5", qty=-1, price=50), row(slip="6", cust="C5", qty=1, price=10)])
    got = d.abc("得意先")
    by = dict(zip(got["コード"], got["区分"]))
    assert by["C1"] == "A"   # 1 件で 70% を超えても、前までの累積は 0% なので A
    assert by["C2"] == "B"   # 前までの累積 約 80%
    assert by["C3"] == "C"   # 前までの累積 約 90.4%
    assert by["C5"] == "C"   # 売上がマイナス
    assert list(db.abc_summary(got)["件数"]) == [1, 1, 3]


def test_tc033_breakdown_by_region_staff_category():
    d = make_db([row(slip="1", region="関東", staff="A", cat="食品", qty=3, price=100, cost=60),
                 row(slip="2", region="関東", staff="B", cat="飲料", qty=1, price=100, cost=90),
                 row(slip="3", region="九州", staff="A", cat="食品", qty=1, price=200, cost=100)])
    reg = d.breakdown("地域").set_index("地域")
    assert reg.loc["関東", "売上"] == 400 and reg.loc["関東", "粗利"] == 130
    assert reg.loc["関東", "粗利率"] == pytest.approx(130 / 400)
    assert reg.loc["九州", "構成比"] == pytest.approx(200 / 600)
    staff = d.breakdown("担当者")
    assert list(staff["担当者"]) == ["A", "B"] and list(staff["明細数"]) == [2, 1]
    assert d.breakdown("商品カテゴリ").set_index("商品カテゴリ").loc["食品", "売上"] == 500


def test_tc034_breakdown_matches_plain_python(two_years):
    d, rows = two_years
    d.set_condition(FilterCondition(P("2025-07"), P("2025-07"), categories=("飲料", "食品")))
    exp = defaultdict(int)
    for r in rows:
        if r["売上日"][:7] == "2025-07" and r["商品カテゴリ"] in ("飲料", "食品"):
            exp[r["担当者"]] += int(r["数量"]) * int(r["単価"])
    got = d.breakdown("担当者").set_index("担当者")["売上"].to_dict()
    assert got == dict(exp)
