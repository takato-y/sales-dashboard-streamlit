"""絞り込み条件（REQ-007 / FN-003）。

期間（年月の範囲）と、担当者・商品カテゴリ・地域の選択で明細を絞り込む。
選択が空の項目は「すべて」を意味する。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import schema as s


@dataclass(frozen=True)
class FilterCondition:
    start: pd.Period | None = None
    end: pd.Period | None = None
    staff: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()

    def describe(self) -> list[tuple[str, str]]:
        """出力ファイルの「条件」欄に書く、項目名と値の組。"""
        def joined(values: tuple[str, ...]) -> str:
            return "、".join(values) if values else "すべて"
        period = f"{self.start or '最初'} 〜 {self.end or '最後'}"
        return [("期間", period), ("担当者", joined(self.staff)),
                ("商品カテゴリ", joined(self.categories)), ("地域", joined(self.regions))]


def apply_dimension_filters(df: pd.DataFrame, cond: FilterCondition) -> pd.DataFrame:
    """期間以外（担当者・商品カテゴリ・地域）で絞り込む。

    前年同月比・前月比は期間の外の月も参照するため、期間を除いた絞り込みを別に用意する。
    """
    mask = pd.Series(True, index=df.index)
    if cond.staff:
        mask &= df[s.COL_STAFF].isin(cond.staff)
    if cond.categories:
        mask &= df[s.COL_CATEGORY].isin(cond.categories)
    if cond.regions:
        mask &= df[s.COL_REGION].isin(cond.regions)
    return df[mask]


def apply_period_filter(df: pd.DataFrame, cond: FilterCondition) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if cond.start is not None:
        mask &= df[s.COL_MONTH] >= cond.start
    if cond.end is not None:
        mask &= df[s.COL_MONTH] <= cond.end
    return df[mask]


def apply_filters(df: pd.DataFrame, cond: FilterCondition) -> pd.DataFrame:
    """すべての条件で絞り込む。"""
    return apply_period_filter(apply_dimension_filters(df, cond), cond)


def options(df: pd.DataFrame, column: str) -> list[str]:
    """絞り込みの選択肢（重複を除き昇順）。"""
    return sorted(df[column].dropna().unique().tolist())


def month_range(df: pd.DataFrame) -> list[pd.Period]:
    """データにある最初の月から最後の月までの全月（途中の欠けも含む）。"""
    if df.empty:
        return []
    return list(pd.period_range(df[s.COL_MONTH].min(), df[s.COL_MONTH].max(), freq="M"))
