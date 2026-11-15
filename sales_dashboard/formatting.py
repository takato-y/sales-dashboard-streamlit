"""画面・出力で共通に使う数値の表示形式。"""

from __future__ import annotations

import math


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def yen(v) -> str:
    """1234567 → 「1,234,567円」。欠損は「—」。"""
    return "—" if _missing(v) else f"{v:,.0f}円"


def man_yen(v) -> str:
    """1234567 → 「123.5万円」。指標の大きな数字を読みやすくする。"""
    return "—" if _missing(v) else f"{v / 10_000:,.1f}万円"


def pct(v, digits: int = 1) -> str:
    """0.2753 → 「27.5%」。欠損（算出できない）は「—」。"""
    return "—" if _missing(v) else f"{v * 100:.{digits}f}%"
