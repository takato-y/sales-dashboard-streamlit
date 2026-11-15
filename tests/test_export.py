"""出力（FN-008・FN-009）と無害化（REQ-011）のテスト。"""

import io
import re
import zipfile
from datetime import datetime

import pandas as pd
import pytest
from openpyxl import load_workbook

from sales_dashboard import db, export, loader
from sales_dashboard.filters import FilterCondition
from tests.helpers import row, to_csv_bytes

DANGEROUS = ["=HYPERLINK(\"http://example.com\",\"x\")", "+SUM(A1)", "-2+3", "@cmd", "\tタブ", "\r復帰", "\n改行"]


def report(rows, cond=FilterCondition()) -> export.ReportData:
    d = db.SalesDB()
    d.load(loader.load_files([("a.csv", to_csv_bytes(rows))]))
    d.set_condition(cond)
    return export.ReportData(cond, d.kpis(), d.monthly_trend(), d.abc("得意先"), d.abc("商品"),
                             d.breakdown("地域"), d.breakdown("担当者"), d.breakdown("商品カテゴリ"))


@pytest.mark.parametrize("value", DANGEROUS)
def test_tc060_neutralize_prefixes(value):
    assert export.neutralize(value) == "'" + value


@pytest.mark.parametrize("value", ["みなと台食品", "A=B", "", 123, -5.5, None])
def test_tc061_neutralize_leaves_safe_values(value):
    assert export.neutralize(value) == value


def test_tc062_excel_has_no_formulas_and_keeps_numbers():
    # 読み込み時に前後の空白（タブ・改行）は除かれるため、ファイル経由では = + - @ で始まる名称を使う
    from_file = DANGEROUS[:4]
    rows = [row(slip=str(i), cust=f"C{i}", cname=name, staff="=1+1", qty=-1 if i == 0 else 2, price=100, cost=70)
            for i, name in enumerate(from_file)]
    r = report(rows, FilterCondition(staff=("=1+1",)))
    # タブ・CR・LF で始まる値は、集計結果に直接入れて確かめる
    extra = pd.DataFrame([[90 + i, f"X{i}", v, 1.0, 0.0, 0.0, 0.0, 1.0, "C"] for i, v in enumerate(DANGEROUS[4:])],
                         columns=r.abc_customer.columns)
    r.abc_customer = pd.concat([r.abc_customer, extra], ignore_index=True)
    data = export.build_excel(r)
    # ブックの XML に数式（<f> 要素）が 1 つもない
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert sheets and not any(re.search(rb"<f[ >]", z.read(n)) for n in sheets)
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["条件と指標", "月次推移", "得意先ABC", "商品ABC", "地域別", "担当者別", "商品カテゴリ別"]
    names = [c.value for c in wb["得意先ABC"]["C"][1:]]
    # XML の改行の正規化により、読み戻すと CR は LF になる（先頭の ' は残る）
    assert sorted(names) == sorted("'" + v.replace("\r", "\n") for v in DANGEROUS)
    sales = [c.value for c in wb["得意先ABC"]["D"][1:]]
    assert -100 in sales and all(isinstance(v, (int, float)) for v in sales)  # マイナスの金額は数値のまま
    cond = {r[0].value: r[1].value for r in wb["条件と指標"].iter_rows()}
    assert cond["担当者"] == "'=1+1"
    assert [c.value for c in wb["担当者別"]["A"][1:]] == ["'=1+1"]


def test_tc063_excel_values_match_views():
    r = report([row(slip="1", qty=3, price=100, cost=60), row(slip="2", qty=1, price=50, cost=10, region="九州")])
    wb = load_workbook(io.BytesIO(export.build_excel(r)))
    kv = {row[0].value: row[1].value for row in wb["条件と指標"].iter_rows()}
    assert kv["売上"] == 350 and kv["粗利"] == 160 and kv["粗利率"] == pytest.approx(160 / 350)
    assert wb["条件と指標"]["B"][[c.value for c in wb["条件と指標"]["A"]].index("粗利率")].number_format == "0.0%"
    region = {r[0].value: r[1].value for r in wb["地域別"].iter_rows(min_row=2)}
    assert region == {"関東": 300, "九州": 50}


def test_tc064_print_html_escapes_text():
    r = report([row(cname="<script>alert(1)</script>", pname="A&B \"商品\"")])
    page = export.build_print_html(r, created=datetime(2026, 1, 5, 9, 0))
    assert "<script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "A&amp;B &quot;商品&quot;" in page
    assert not re.search(r"(src|href)\s*=", page)  # 外部の資源を読み込まない
    assert "作成 2026-01-05 09:00" in page and "@page" in page


def test_tc065_empty_report_is_exportable():
    r = report([row()], FilterCondition(staff=("いない担当",)))
    assert export.build_excel(r)[:2] == b"PK"
    assert "売上分析レポート" in export.build_print_html(r)
