"""ABC 分析・地域別・担当者別（FN-006・FN-007）のテスト。"""

import csv
from collections import defaultdict

import pandas as pd
import pytest

from sales_dashboard import analysis, generator, loader
from sales_dashboard import schema as s
from tests.helpers import row, to_csv_bytes


def load_rows(rows):
    return loader.load_files([("a.csv", to_csv_bytes(rows))]).data


def test_tc030_abc_matches_plain_python(tmp_path):
    path = tmp_path / "s.csv"
    generator.generate_sales(seed=21, months=12, lines_per_month=500).to_csv(path, index=False)
    data = loader.load_paths([str(path)]).data
    got = analysis.abc_analysis(data, s.COL_CUST_CODE, s.COL_CUST_NAME)

    sales = defaultdict(int)
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            sales[r["得意先コード"]] += int(r["数量"]) * int(r["単価"])
    ordered = sorted(sales.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(sales.values())
    cum, expected = 0.0, []
    for code, v in ordered:
        before = cum
        cum += v / total
        expected.append((code, v, "A" if before < 0.7 else "B" if before < 0.9 else "C"))
    assert list(got["コード"]) == [e[0] for e in expected]
    assert list(got["売上"]) == [e[1] for e in expected]
    assert list(got["区分"]) == [e[2] for e in expected]
    assert got["累積構成比"].iloc[-1] == pytest.approx(1.0)


def test_tc031_abc_boundary_and_negative():
    # 構成比 80%・10%・6%・4%、さらに返品で売上がマイナスの得意先
    rows = [row(slip="1", cust="C1", qty=80, price=100), row(slip="2", cust="C2", qty=10, price=100),
            row(slip="3", cust="C3", qty=6, price=100), row(slip="4", cust="C4", qty=4, price=100),
            row(slip="5", cust="C5", qty=-1, price=50), row(slip="6", cust="C5", qty=1, price=10)]
    got = analysis.abc_analysis(load_rows(rows), s.COL_CUST_CODE, s.COL_CUST_NAME)
    by = dict(zip(got["コード"], got["区分"]))
    assert by["C1"] == "A"   # 1 件で 70% を超えても、前までの累積は 0% なので A
    assert by["C2"] == "B"   # 前までの累積 80%（70% 以上 90% 未満）
    assert by["C3"] == "C"   # 前までの累積 約 90.4%
    assert by["C5"] == "C"   # 売上がマイナス
    summary = analysis.abc_summary(got)
    assert list(summary["件数"]) == [1, 1, 3]


def test_tc032_abc_uses_latest_name():
    rows = [row(slip="1", cust="C1", cname="旧社名", day="2025-01-06"),
            row(slip="2", cust="C1", cname="新社名", day="2025-02-03")]
    got = analysis.abc_analysis(load_rows(rows), s.COL_CUST_CODE, s.COL_CUST_NAME)
    assert got.iloc[0]["名称"] == "新社名"


def test_tc033_breakdown_by_region_and_staff():
    rows = [row(slip="1", region="関東", staff="A", qty=3, price=100, cost=60),
            row(slip="2", region="関東", staff="B", qty=1, price=100, cost=90),
            row(slip="3", region="九州", staff="A", qty=1, price=200, cost=100)]
    data = load_rows(rows)
    reg = analysis.breakdown(data, s.COL_REGION).set_index(s.COL_REGION)
    assert reg.loc["関東", "売上"] == 400 and reg.loc["関東", "粗利"] == 130
    assert reg.loc["関東", "粗利率"] == pytest.approx(130 / 400)
    assert reg.loc["九州", "構成比"] == pytest.approx(200 / 600)
    staff = analysis.breakdown(data, s.COL_STAFF)
    assert list(staff[s.COL_STAFF]) == ["A", "B"] and list(staff["明細数"]) == [2, 1]


def test_tc034_empty_inputs():
    empty = loader.load_files([]).data
    assert analysis.abc_analysis(empty, s.COL_CUST_CODE, s.COL_CUST_NAME).empty
    assert analysis.breakdown(empty, s.COL_REGION).empty
    assert isinstance(analysis.abc_summary(pd.DataFrame(columns=analysis.ABC_COLUMNS)), pd.DataFrame)
