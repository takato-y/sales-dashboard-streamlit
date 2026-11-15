"""売上分析ダッシュボードの業務ロジック。

画面（Streamlit）に依存しない処理だけを置く。読み込み・検証（loader）、
絞り込み条件（filters）、SQL による集計（db と sql/ のビュー）、グラフ（charts）、
出力（export）、架空データの生成（generator）に分かれる。
"""

__version__ = "1.0.0"
