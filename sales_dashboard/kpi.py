"""指標と月次推移（REQ-003・REQ-004 / FN-004・FN-005）。

指標の計算式は docs/02_基本設計.md の「指標の定義」と一致させること。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import schema as s
from .filters import FilterCondition, apply_dimension_filters, apply_period_filter


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    """割合。分母が 0・欠損・マイナスのときは算出しない（None）。"""
    if numerator is None or denominator is None or pd.isna(denominator) or denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def margin(profit: float, sales: float) -> float | None:
    """粗利率 ＝ 粗利 ÷ 売上。売上が 0 以下のときは算出しない。"""
    return ratio(profit, sales)


@dataclass
class KpiSummary:
    period_start: pd.Period | None
    period_end: pd.Period | None
    rows: int
    sales: float
    profit: float
    margin: float | None
    target_month: pd.Period | None      # 前年同月比・前月比の対象月（期間の最終月）
    month_sales: float | None
    prev_month_sales: float | None      # データにその月がなければ None
    prev_year_sales: float | None
    mom: float | None                   # 前月比 ＝ 対象月の売上 ÷ 前月の売上
    yoy: float | None                   # 前年同月比 ＝ 対象月の売上 ÷ 前年同月の売上


def _month_sales(dim_df: pd.DataFrame, month: pd.Period, available: set) -> float | None:
    """その月の売上。読み込んだデータにその月が 1 行もなければ None（0 とは区別する）。"""
    if month not in available:
        return None
    return float(dim_df.loc[dim_df[s.COL_MONTH] == month, s.COL_SALES].sum())


def compute_kpis(data: pd.DataFrame, cond: FilterCondition) -> KpiSummary:
    """読み込んだ全明細（data）と絞り込み条件から指標を計算する。

    期間の売上・粗利は全条件で絞り込んだ明細から、前年同月比・前月比は
    期間以外の条件で絞り込んだ明細から計算する（期間外の月を参照するため）。
    """
    dim_df = apply_dimension_filters(data, cond)
    period_df = apply_period_filter(dim_df, cond)
    available = set(data[s.COL_MONTH].unique()) if not data.empty else set()

    sales = float(period_df[s.COL_SALES].sum())
    profit = float(period_df[s.COL_PROFIT].sum())

    target = cond.end
    if target is None and available:
        target = max(available)
    month_sales = prev_month = prev_year = None
    if target is not None:
        month_sales = _month_sales(dim_df, target, available)
        prev_month = _month_sales(dim_df, target - 1, available)
        prev_year = _month_sales(dim_df, target - 12, available)
    return KpiSummary(
        period_start=cond.start, period_end=cond.end, rows=len(period_df),
        sales=sales, profit=profit, margin=margin(profit, sales),
        target_month=target, month_sales=month_sales,
        prev_month_sales=prev_month, prev_year_sales=prev_year,
        mom=ratio(month_sales, prev_month), yoy=ratio(month_sales, prev_year),
    )


def monthly_trend(data: pd.DataFrame, cond: FilterCondition) -> pd.DataFrame:
    """期間内の月ごとの売上・粗利・粗利率と、前年同月の売上・前年同月比。

    読み込んだデータに含まれない月は値を空欄（NaN）にする。データはあるが
    絞り込みの結果が 0 件の月は 0 とする。
    """
    cols = ["年月", "売上", "粗利", "粗利率", "前年同月売上", "前年同月比"]
    if data.empty:
        return pd.DataFrame(columns=cols)
    dim_df = apply_dimension_filters(data, cond)
    available = set(data[s.COL_MONTH].unique())
    start = cond.start or min(available)
    end = cond.end or max(available)
    months = pd.period_range(start, end, freq="M")

    by_month = dim_df.groupby(s.COL_MONTH)[[s.COL_SALES, s.COL_PROFIT]].sum()
    rows = []
    for m in months:
        if m in available:
            sales = float(by_month[s.COL_SALES].get(m, 0.0))
            profit = float(by_month[s.COL_PROFIT].get(m, 0.0))
        else:
            sales = profit = float("nan")
        prev = m - 12
        prev_sales = float(by_month[s.COL_SALES].get(prev, 0.0)) if prev in available else float("nan")
        rows.append([m, sales, profit, margin(profit, sales) if sales == sales else None,
                     prev_sales, ratio(sales, prev_sales) if sales == sales else None])
    out = pd.DataFrame(rows, columns=cols)
    out["粗利率"] = out["粗利率"].astype("float64")
    out["前年同月比"] = out["前年同月比"].astype("float64")
    return out
