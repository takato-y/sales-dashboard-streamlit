"""絞り込み条件（REQ-007 / FN-003）。

期間（年月の範囲）と、担当者・商品カテゴリ・地域の選択を持つ。選択が空の項目は「すべて」。
絞り込み自体は SQL のビュー（v_dim_line・v_filtered_line）が行う。この条件は
SalesDB.set_condition() で w_cond_* 表に書き込まれる。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


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
