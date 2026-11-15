"""ABC 分析と地域別・担当者別の集計（REQ-005・REQ-006 / FN-006・FN-007）。

ABC の区分の決め方は docs/adr/0002 を参照。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema as s

ABC_A_LIMIT = 0.70  # 前までの累積構成比がこれ未満なら A
ABC_B_LIMIT = 0.90  # 前までの累積構成比がこれ未満なら B（A 以外）

ABC_COLUMNS = ["順位", "コード", "名称", "売上", "粗利", "粗利率", "構成比", "累積構成比", "区分"]


def _safe_div(a: pd.Series, b) -> pd.Series:
    """割り算。分母が 0 以下の要素は NaN にする。"""
    b = pd.Series(b, index=a.index) if np.isscalar(b) else b
    return (a / b.where(b > 0)).astype("float64")


def abc_analysis(df: pd.DataFrame, code_col: str, name_col: str) -> pd.DataFrame:
    """コード単位に売上を集計し、ABC の区分を付ける。

    名称はそのコードの最も新しい売上日の明細の名称を使う（途中で名称が変わった場合に備える）。
    """
    if df.empty:
        return pd.DataFrame(columns=ABC_COLUMNS)
    names = df.sort_values(s.COL_DATE).groupby(code_col)[name_col].last()
    g = df.groupby(code_col)[[s.COL_SALES, s.COL_PROFIT]].sum()
    g["名称"] = names
    g = g.reset_index().rename(columns={code_col: "コード", s.COL_SALES: "売上", s.COL_PROFIT: "粗利"})
    g = g.sort_values(["売上", "コード"], ascending=[False, True], kind="mergesort").reset_index(drop=True)

    total = g["売上"].sum()
    g["粗利率"] = _safe_div(g["粗利"], g["売上"])
    g["構成比"] = _safe_div(g["売上"], total)
    g["累積構成比"] = g["構成比"].cumsum()
    before = g["累積構成比"] - g["構成比"]
    g["区分"] = np.select([before < ABC_A_LIMIT, before < ABC_B_LIMIT], ["A", "B"], default="C")
    g.loc[(g["売上"] <= 0) | g["構成比"].isna(), "区分"] = "C"
    g.insert(0, "順位", np.arange(1, len(g) + 1))
    return g[ABC_COLUMNS]


def abc_summary(abc: pd.DataFrame) -> pd.DataFrame:
    """区分ごとの件数と売上・構成比。"""
    rows = []
    total = abc["売上"].sum() if not abc.empty else 0
    for k in ("A", "B", "C"):
        part = abc[abc["区分"] == k]
        sales = float(part["売上"].sum())
        rows.append([k, len(part), sales, sales / total if total > 0 else np.nan])
    return pd.DataFrame(rows, columns=["区分", "件数", "売上", "構成比"])


def breakdown(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """指定した列（地域・担当者・商品カテゴリなど）ごとの売上・粗利・粗利率・構成比。"""
    cols = [by, "売上", "粗利", "粗利率", "構成比", "明細数"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    g = df.groupby(by).agg(売上=(s.COL_SALES, "sum"), 粗利=(s.COL_PROFIT, "sum"), 明細数=(s.COL_SALES, "size"))
    g = g.reset_index().sort_values(["売上", by], ascending=[False, True], kind="mergesort")
    g["粗利率"] = _safe_div(g["粗利"], g["売上"])
    g["構成比"] = _safe_div(g["売上"], g["売上"].sum())
    return g[cols].reset_index(drop=True)
