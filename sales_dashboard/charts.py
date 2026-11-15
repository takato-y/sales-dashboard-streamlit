"""グラフの作成（Plotly）。画面と切り離してテストできるよう、図の組み立てだけを行う。

色は 1 系列目を青、比較対象（前年）を灰色にする。2 つの縦軸を持つグラフは使わない
（売上と粗利は別のグラフに分ける）。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

BLUE = "#2a78d6"
GRAY = "#8a8984"
# ABC の区分（順序のある分類なので同じ色相の濃淡で表す）
ABC_COLORS = {"A": "#1c5cab", "B": "#5b9be6", "C": "#b5d3f5"}
FONT = "Noto Sans JP, Noto Sans CJK JP, Hiragino Sans, Meiryo, sans-serif"


def _layout(fig: go.Figure, title: str, height: int = 360) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=16)),
        font=dict(family=FONT, size=13, color="#2b2b2a"),
        height=height, margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
        hoverlabel=dict(font_family=FONT),
    )
    fig.update_xaxes(showgrid=False, linecolor="#d6d5d0")
    fig.update_yaxes(gridcolor="#ecebe7", zeroline=True, zerolinecolor="#d6d5d0")
    return fig


def month_labels(trend: pd.DataFrame) -> list[str]:
    """横軸の月の表示（「2025/01」）。日付として解釈されて英語表記になるのを避ける。"""
    return [str(ym).replace("-", "/") for ym in trend["年月"]]


def trend_figure(trend: pd.DataFrame) -> go.Figure:
    """月別の売上を、前年同月の売上と並べた折れ線。単位は万円。"""
    x = month_labels(trend)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=trend["前年同月売上"] / 10_000, name="前年同月", mode="lines+markers",
        line=dict(color=GRAY, width=2, dash="dash"), marker=dict(size=8),
        hovertemplate="%{x}<br>前年同月：%{y:,.1f}万円<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=trend["売上"] / 10_000, name="売上", mode="lines+markers",
        line=dict(color=BLUE, width=2), marker=dict(size=8),
        hovertemplate="%{x}<br>売上：%{y:,.1f}万円<extra></extra>"))
    fig.update_yaxes(title_text="万円", tickformat=",")
    fig.update_xaxes(type="category")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, "月別の売上（前年同月との比較）")


def profit_figure(trend: pd.DataFrame) -> go.Figure:
    """月別の粗利の棒グラフ。粗利率はホバーで示す。"""
    x = month_labels(trend)
    fig = go.Figure(go.Bar(
        x=x, y=trend["粗利"] / 10_000, name="粗利", marker=dict(color=BLUE, cornerradius=4),
        customdata=(trend["粗利率"] * 100).round(1),
        hovertemplate="%{x}<br>粗利：%{y:,.1f}万円<br>粗利率：%{customdata}%<extra></extra>"))
    fig.update_yaxes(title_text="万円", tickformat=",")
    fig.update_xaxes(type="category")
    fig.update_layout(bargap=0.35)
    return _layout(fig, "月別の粗利", height=300)


def abc_figure(abc: pd.DataFrame, title: str, top_n: int = 20) -> go.Figure:
    """売上上位の横棒グラフ。棒の濃さで ABC の区分を示す。"""
    top = abc.head(top_n).iloc[::-1]  # 横棒は下から描かれるため逆順にする
    fig = go.Figure()
    for k in ("A", "B", "C"):
        part = top[top["区分"] == k]
        if part.empty:
            continue
        fig.add_trace(go.Bar(
            y=part["名称"], x=part["売上"] / 10_000, orientation="h", name=f"区分 {k}",
            marker=dict(color=ABC_COLORS[k], cornerradius=4),
            customdata=(part["累積構成比"] * 100).round(1),
            hovertemplate="%{y}<br>売上：%{x:,.1f}万円<br>累積構成比：%{customdata}%<extra></extra>"))
    fig.update_xaxes(title_text="万円", tickformat=",", gridcolor="#ecebe7", showgrid=True)
    fig.update_yaxes(categoryorder="array", categoryarray=list(top["名称"]), showgrid=False)
    fig.update_layout(barmode="overlay", bargap=0.3)
    return _layout(fig, title, height=max(320, 26 * len(top) + 90))


def breakdown_figure(df: pd.DataFrame, by: str, title: str) -> go.Figure:
    """地域別・担当者別などの横棒グラフ。粗利率はホバーで示す。"""
    d = df.iloc[::-1]
    fig = go.Figure(go.Bar(
        y=d[by], x=d["売上"] / 10_000, orientation="h", name="売上",
        marker=dict(color=BLUE, cornerradius=4),
        customdata=(d["粗利率"] * 100).round(1),
        hovertemplate="%{y}<br>売上：%{x:,.1f}万円<br>粗利率：%{customdata}%<extra></extra>"))
    fig.update_xaxes(title_text="万円", tickformat=",", gridcolor="#ecebe7", showgrid=True)
    fig.update_layout(bargap=0.3, showlegend=False)
    return _layout(fig, title, height=max(260, 34 * len(d) + 90))
