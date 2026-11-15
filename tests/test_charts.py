"""グラフの組み立て（FN-011 の一部）のテスト。SQL のビューの結果からグラフを作れることを確かめる。"""

import pandas as pd
import pytest

from sales_dashboard import charts, db, loader
from sales_dashboard.filters import FilterCondition
from tests.helpers import row, to_csv_bytes


def test_tc050_figures_are_built_from_view_results():
    d = db.SalesDB()
    d.load(loader.load_files([("a.csv", to_csv_bytes([
        row(slip="1", day="2025-01-06"), row(slip="2", day="2025-03-03", cust="C2", region="九州")]))]))
    d.set_condition(FilterCondition(pd.Period("2025-01", "M"), pd.Period("2025-03", "M")))
    trend = d.monthly_trend()
    fig = charts.trend_figure(trend)
    assert list(fig.data[1].x) == ["2025/01", "2025/02", "2025/03"]  # 横軸は日付ではなく文字の分類
    assert fig.layout.xaxis.type == "category"
    assert charts.profit_figure(trend).data[0].y[0] == pytest.approx(0.003)  # 粗利 30 円 → 0.003 万円
    assert len(charts.abc_figure(d.abc("得意先"), "t").data) >= 1
    assert list(charts.breakdown_figure(d.breakdown("地域"), "地域", "t").data[0].y) == ["関東", "九州"]  # 横棒は下から描くため表の逆順
