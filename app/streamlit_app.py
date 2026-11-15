"""売上分析ダッシュボードの画面（Streamlit）。

集計の処理はすべて sales_dashboard パッケージにあり、この画面は呼び出しと表示だけを行う。
起動: streamlit run app/streamlit_app.py --server.address 127.0.0.1
認証はないため、ローカル（127.0.0.1）専用で使う。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sales_dashboard import analysis, charts, generator, kpi, loader  # noqa: E402
from sales_dashboard import schema as s  # noqa: E402
from sales_dashboard.filters import FilterCondition, apply_filters, month_range, options  # noqa: E402
from sales_dashboard.formatting import man_yen, pct, yen  # noqa: E402

st.set_page_config(page_title="売上分析ダッシュボード", layout="wide")

st.markdown("""
<style>
  html, body, [class*="css"] { font-family: "Noto Sans JP", "Noto Sans CJK JP", "Hiragino Sans", Meiryo, sans-serif; }
  [data-testid="stMetricValue"] { font-size: 1.6rem; }
  .block-container { padding-top: 2.2rem; }
</style>
""", unsafe_allow_html=True)

SAMPLE = "サンプルデータ（架空・2年分）"
UPLOAD = "ファイルを読み込む"


@st.cache_data(show_spinner="読み込んでいます…")
def load_uploaded(sources: tuple[tuple[str, bytes], ...]) -> loader.LoadResult:
    return loader.load_files(list(sources))


@st.cache_data(show_spinner="サンプルデータを作成しています…")
def load_sample() -> loader.LoadResult:
    df = generator.generate_sales(seed=42, start="2024-01", months=24, lines_per_month=1200)
    month = df[s.COL_DATE].str.slice(0, 7)
    sources = [(f"sales_{m}.csv", g.to_csv(index=False).encode("utf-8")) for m, g in df.groupby(month)]
    return loader.load_files(sources)


def money_table(df: pd.DataFrame, money=(), percent=(), height=None):
    """金額は「円」、割合は「%」で表示する表。"""
    fmt = {c: (lambda v: yen(v)) for c in money if c in df.columns}
    fmt.update({c: (lambda v: pct(v)) for c in percent if c in df.columns})
    kwargs = {"height": height} if height else {}
    st.dataframe(df.style.format(fmt), hide_index=True, width="stretch", **kwargs)


# ---------------------------------------------------------------- サイドバー：読み込み

with st.sidebar:
    st.header("データ")
    source = st.radio("使うデータ", [SAMPLE, UPLOAD], label_visibility="collapsed")
    if source == UPLOAD:
        files = st.file_uploader("売上明細（CSV・Excel、複数可）", type=["csv", "xlsx"],
                                 accept_multiple_files=True)
        if not files:
            st.info("売上明細のファイルを選んでください。列の形式は README の「使い方」に記載しています。")
            st.stop()
        result = load_uploaded(tuple((f.name, f.getvalue()) for f in files))
    else:
        result = load_sample()

data = result.data

st.title("売上分析ダッシュボード")
summary = f"読み込み {len(result.files_read)} ファイル・{result.total_rows:,} 行　／　集計対象 {len(data):,} 行"
if len(result.rejected) or result.file_errors:
    st.warning(f"{summary}　／　除外 {len(result.rejected):,} 行・読めなかったファイル "
               f"{len(result.file_errors)} 件（詳細は「取込結果」タブ）")
else:
    st.caption(summary)

if data.empty:
    st.error("集計できる明細がありません。「取込結果」の理由を確認してください。")

# ---------------------------------------------------------------- サイドバー：絞り込み

with st.sidebar:
    st.header("絞り込み")
    months = month_range(data)
    if months:
        labels = [str(m) for m in months]
        default_start = labels[max(0, len(labels) - 12)]  # 初期表示は直近 12 か月
        start_label, end_label = st.select_slider("期間", options=labels, value=(default_start, labels[-1]))
        start, end = pd.Period(start_label, "M"), pd.Period(end_label, "M")
    else:
        start = end = None
    staff = st.multiselect("担当者", options(data, s.COL_STAFF), placeholder="すべて")
    cats = st.multiselect("商品カテゴリ", options(data, s.COL_CATEGORY), placeholder="すべて")
    regions = st.multiselect("地域", options(data, s.COL_REGION), placeholder="すべて")
    st.caption("選ばない項目は「すべて」として集計します。")

cond = FilterCondition(start, end, tuple(staff), tuple(cats), tuple(regions))
filtered = apply_filters(data, cond)
k = kpi.compute_kpis(data, cond)
trend = kpi.monthly_trend(data, cond)
abc_cust = analysis.abc_analysis(filtered, s.COL_CUST_CODE, s.COL_CUST_NAME)
abc_prod = analysis.abc_analysis(filtered, s.COL_PROD_CODE, s.COL_PROD_NAME)
by_region = analysis.breakdown(filtered, s.COL_REGION)
by_staff = analysis.breakdown(filtered, s.COL_STAFF)
by_cat = analysis.breakdown(filtered, s.COL_CATEGORY)

tab_overview, tab_abc, tab_breakdown, tab_load = st.tabs(["概要", "ABC分析", "地域・担当別", "取込結果"])

# ---------------------------------------------------------------- 概要

with tab_overview:
    st.caption(f"期間 {cond.start} 〜 {cond.end}　／　集計対象 {k.rows:,} 行")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("売上", man_yen(k.sales), help="期間内の 数量×単価 の合計")
    c2.metric("粗利", man_yen(k.profit), help="売上 − 原価（数量×原価単価）")
    c3.metric("粗利率", pct(k.margin), help="粗利 ÷ 売上")
    yoy_delta = None if k.yoy is None else f"{(k.yoy - 1) * 100:+.1f}%"
    mom_delta = None if k.mom is None else f"{(k.mom - 1) * 100:+.1f}%"
    c4.metric(f"前年同月比（{k.target_month}）", pct(k.yoy), yoy_delta,
              help="期間の最終月の売上 ÷ 前年同月の売上。前年同月のデータがない場合は「—」")
    c5.metric(f"前月比（{k.target_month}）", pct(k.mom), mom_delta,
              help="期間の最終月の売上 ÷ 前月の売上。前月のデータがない場合は「—」")
    if not trend.empty:
        st.plotly_chart(charts.trend_figure(trend), width="stretch")
        st.plotly_chart(charts.profit_figure(trend), width="stretch")
        with st.expander("月次推移の表"):
            t = trend.assign(年月=trend["年月"].astype(str))
            money_table(t, money=("売上", "粗利", "前年同月売上"), percent=("粗利率", "前年同月比"))

# ---------------------------------------------------------------- ABC分析

with tab_abc:
    st.caption("売上の多い順に並べ、その 1 件より前までの累積構成比が 70% 未満を A、90% 未満を B、"
               "それ以外を C としています。")
    kind = st.radio("対象", ["得意先", "商品"], horizontal=True)
    abc = abc_cust if kind == "得意先" else abc_prod
    left, right = st.columns([3, 2])
    with left:
        if not abc.empty:
            st.plotly_chart(charts.abc_figure(abc, f"{kind}別の売上（上位20）"), width="stretch")
    with right:
        st.markdown("**区分ごとの件数と売上**")
        money_table(analysis.abc_summary(abc), money=("売上",), percent=("構成比",))
    st.markdown(f"**{kind}別の一覧**")
    money_table(abc, money=("売上", "粗利"), percent=("粗利率", "構成比", "累積構成比"), height=380)

# ---------------------------------------------------------------- 地域・担当別

with tab_breakdown:
    left, right = st.columns(2)
    with left:
        if not by_region.empty:
            st.plotly_chart(charts.breakdown_figure(by_region, s.COL_REGION, "地域別の売上"), width="stretch")
        money_table(by_region, money=("売上", "粗利"), percent=("粗利率", "構成比"))
    with right:
        if not by_staff.empty:
            st.plotly_chart(charts.breakdown_figure(by_staff, s.COL_STAFF, "担当者別の売上"), width="stretch")
        money_table(by_staff, money=("売上", "粗利"), percent=("粗利率", "構成比"))
    st.markdown("**商品カテゴリ別**")
    money_table(by_cat, money=("売上", "粗利"), percent=("粗利率", "構成比"))

# ---------------------------------------------------------------- 取込結果

with tab_load:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("読み込んだファイル", f"{len(result.files_read)} 件")
    c2.metric("集計対象の行", f"{len(data):,} 行")
    c3.metric("除外した行", f"{len(result.rejected):,} 行")
    c4.metric("空行（読み飛ばし）", f"{result.blank_rows:,} 行")
    if result.file_errors:
        st.markdown("**読めなかったファイル**")
        st.dataframe(pd.DataFrame([(e.file, e.reason) for e in result.file_errors],
                                  columns=["ファイル名", "理由"]), hide_index=True, width="stretch")
    if len(result.rejected):
        st.markdown("**除外した行**（行番号は見出し行を 1 行目として数えています）")
        st.dataframe(result.rejected, hide_index=True, width="stretch")
        st.download_button("除外した行を CSV で保存", result.rejected.to_csv(index=False).encode("utf-8-sig"),
                           file_name="除外した行.csv", mime="text/csv")
    elif not result.file_errors:
        st.success("すべての行を集計対象にしました。")
