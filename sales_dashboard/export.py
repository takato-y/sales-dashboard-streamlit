"""絞り込んだ結果の出力（REQ-008・REQ-009・REQ-011 / FN-008・FN-009）。

得意先名・商品名などは利用者のファイルに由来するため、出力時に無害化する（docs/adr/0003）。
- Excel: = + - @ タブ・CR・LF で始まる文字列の先頭に ' を付け、セルの型を文字列に固定する
- 印刷用 HTML: すべての文字列を HTML の特殊文字として変換し、外部の資源は読み込まない
"""

from __future__ import annotations

import html
import io
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import KpiSummary
from .filters import FilterCondition
from .formatting import man_yen, pct, yen

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
MONEY_COLUMNS = {"売上", "粗利", "前年同月売上", "前月売上", "対象月の売上"}
PERCENT_COLUMNS = {"粗利率", "構成比", "累積構成比", "前年同月比", "前月比"}
HEADER_FILL = PatternFill("solid", fgColor="E8EEF7")


def neutralize(value):
    """数式として解釈されうる文字列の先頭に ' を付ける。文字列以外はそのまま返す。"""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


@dataclass
class ReportData:
    """出力する集計結果一式（SQL のビューから読んだもの）。"""

    cond: FilterCondition
    kpi: KpiSummary
    trend: pd.DataFrame
    abc_customer: pd.DataFrame
    abc_product: pd.DataFrame
    by_region: pd.DataFrame
    by_staff: pd.DataFrame
    by_category: pd.DataFrame


def kpi_rows(k: KpiSummary) -> list[tuple[str, object]]:
    """指標を「項目・値」の組にする（値は数値のまま。割合は 0〜1）。"""
    return [
        ("期間", f"{k.period_start or '—'} 〜 {k.period_end or '—'}"),
        ("集計対象の行数", k.rows),
        ("売上", k.sales), ("粗利", k.profit), ("粗利率", k.margin),
        ("対象月", k.target_month or "—"),
        ("対象月の売上", k.month_sales), ("前年同月売上", k.prev_year_sales), ("前年同月比", k.yoy),
        ("前月売上", k.prev_month_sales), ("前月比", k.mom),
    ]


# ---------------------------------------------------------------- Excel

def _write_cell(ws, row: int, col: int, value, header: str | None = None):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ws.cell(row=row, column=col, value=None)
    if hasattr(value, "item"):  # numpy の数値を Python の数値に
        value = value.item()
    cell = ws.cell(row=row, column=col, value=neutralize(value))
    if isinstance(cell.value, str):
        cell.data_type = "s"  # 先頭が = でも数式として書き出さない
    elif header in MONEY_COLUMNS:
        cell.number_format = "#,##0"
    elif header in PERCENT_COLUMNS:
        cell.number_format = "0.0%"
    return cell


def _write_table(ws, df: pd.DataFrame) -> None:
    for j, name in enumerate(df.columns, start=1):
        c = _write_cell(ws, 1, j, str(name))
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center")
    for i, values in enumerate(df.itertuples(index=False, name=None), start=2):
        for j, (name, v) in enumerate(zip(df.columns, values), start=1):
            _write_cell(ws, i, j, v, header=str(name))
    for j, name in enumerate(df.columns, start=1):
        width = max([len(str(name))] + [len(str(v)) for v in df.iloc[:200, j - 1]]) if len(df) else len(str(name))
        ws.column_dimensions[get_column_letter(j)].width = min(40, max(10, width * 1.6 + 2))
    ws.freeze_panes = "A2"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_excel(r: ReportData) -> bytes:
    """集計結果を 1 つの Excel ブックにして返す。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "条件と指標"
    rows = [("絞り込み条件", "")] + r.cond.describe() + [("", ""), ("指標", "")] + kpi_rows(r.kpi)
    for i, (label, value) in enumerate(rows, start=1):
        _write_cell(ws, i, 1, label).font = Font(bold=label in ("絞り込み条件", "指標"))
        _write_cell(ws, i, 2, value, header=label)
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 40

    for title, df in (("月次推移", r.trend), ("得意先ABC", r.abc_customer), ("商品ABC", r.abc_product),
                      ("地域別", r.by_region), ("担当者別", r.by_staff), ("商品カテゴリ別", r.by_category)):
        _write_table(wb.create_sheet(title), df)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- 印刷用 HTML

def _fmt(col: str, v) -> str:
    if col in MONEY_COLUMNS:
        return yen(v)
    if col in PERCENT_COLUMNS:
        return pct(v)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _html_table(df: pd.DataFrame, limit: int | None = None) -> str:
    d = df.head(limit) if limit else df
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in d.columns)
    body = []
    for values in d.itertuples(index=False, name=None):
        cells = []
        for c, v in zip(d.columns, values):
            if hasattr(v, "item"):
                v = v.item()
            cls = ' class="num"' if isinstance(v, (int, float)) else ""
            cells.append(f"<td{cls}>{html.escape(_fmt(str(c), v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


PRINT_CSS = """
@page { size: A4 portrait; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans JP", "Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif;
       color: #222; font-size: 10.5pt; margin: 0 auto; max-width: 190mm; padding: 8mm 0; background: #fff; }
h1 { font-size: 17pt; margin: 0 0 2mm; }
h2 { font-size: 12.5pt; margin: 7mm 0 2mm; padding-left: 2mm; border-left: 4px solid #2a78d6; break-after: avoid; }
.meta { color: #555; font-size: 9pt; margin-bottom: 4mm; }
.cond { display: grid; grid-template-columns: max-content 1fr; gap: 1mm 5mm; font-size: 9.5pt; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 2mm; margin-top: 3mm; }
.kpi { border: 1px solid #d6d5d0; border-radius: 2mm; padding: 2mm 3mm; }
.kpi .label { font-size: 8.5pt; color: #555; white-space: nowrap; }
.kpi .value { font-size: 12pt; font-weight: bold; margin-top: 1mm; white-space: nowrap; }
.kpi .sub { font-size: 7.5pt; color: #555; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; break-inside: auto; }
th, td { border: 1px solid #d6d5d0; padding: 1.2mm 2mm; }
th { background: #e8eef7; font-weight: bold; }
tr { break-inside: avoid; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.note { color: #555; font-size: 8.5pt; margin-top: 2mm; }
@media print { .noprint { display: none; } body { padding: 0; } }
"""


def build_print_html(r: ReportData, created: datetime | None = None, top_n: int = 20) -> str:
    """ブラウザで開いて印刷（PDF に保存）するための HTML を返す。"""
    created = created or datetime.now()
    k = r.kpi
    esc = html.escape
    cond = "".join(f"<div>{esc(a)}</div><div>{esc(b)}</div>" for a, b in r.cond.describe())
    target = f"対象月 {k.target_month or '—'}"
    cards = [("売上", man_yen(k.sales), yen(k.sales)), ("粗利", man_yen(k.profit), yen(k.profit)),
             ("粗利率", pct(k.margin), ""), ("前年同月比", pct(k.yoy), target), ("前月比", pct(k.mom), target)]
    kpis = "".join(f'<div class="kpi"><div class="label">{esc(a)}</div><div class="value">{esc(b)}</div>'
                   f'<div class="sub">{esc(c)}</div></div>' for a, b, c in cards)
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>売上分析レポート</title>
<style>{PRINT_CSS}</style>
</head>
<body>
<p class="noprint note">ブラウザの印刷機能で「PDF に保存」を選ぶと、A4 縦の PDF になります。</p>
<h1>売上分析レポート</h1>
<div class="meta">作成 {esc(created.strftime("%Y-%m-%d %H:%M"))}　／　集計対象 {k.rows:,} 行</div>
<div class="cond">{cond}</div>
<div class="kpis">{kpis}</div>
<h2>月次推移</h2>
{_html_table(r.trend)}
<h2>得意先別（上位{top_n}・ABC 分析）</h2>
{_html_table(r.abc_customer, top_n)}
<h2>商品別（上位{top_n}・ABC 分析）</h2>
{_html_table(r.abc_product, top_n)}
<h2>地域別</h2>
{_html_table(r.by_region)}
<h2>担当者別</h2>
{_html_table(r.by_staff)}
<h2>商品カテゴリ別</h2>
{_html_table(r.by_category)}
<p class="note">粗利率 ＝ 粗利 ÷ 売上。前年同月比 ＝ 対象月の売上 ÷ 前年同月の売上。「—」は算出できないことを表します。</p>
</body>
</html>
"""
