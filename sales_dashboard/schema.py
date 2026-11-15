"""入力データの列定義（docs/04_入力データ仕様.md と対応）。"""

from __future__ import annotations

# 入力ファイルの必須列（この順で正規化後の表に並べる）
COL_SLIP = "伝票番号"
COL_LINE = "行番号"
COL_DATE = "売上日"
COL_CUST_CODE = "得意先コード"
COL_CUST_NAME = "得意先名"
COL_REGION = "地域"
COL_STAFF = "担当者"
COL_PROD_CODE = "商品コード"
COL_PROD_NAME = "商品名"
COL_CATEGORY = "商品カテゴリ"
COL_QTY = "数量"
COL_PRICE = "単価"
COL_COST = "原価単価"

REQUIRED_COLUMNS: list[str] = [
    COL_SLIP, COL_LINE, COL_DATE, COL_CUST_CODE, COL_CUST_NAME, COL_REGION,
    COL_STAFF, COL_PROD_CODE, COL_PROD_NAME, COL_CATEGORY, COL_QTY, COL_PRICE, COL_COST,
]

# 前後の空白除去に加え、全角英数を半角にそろえる列（コード類）
CODE_COLUMNS = [COL_SLIP, COL_CUST_CODE, COL_PROD_CODE]
# 前後の空白除去だけを行う文字列の列
TEXT_COLUMNS = [COL_CUST_NAME, COL_REGION, COL_STAFF, COL_PROD_NAME, COL_CATEGORY]

# 読み込み時に付ける列（金額・年月は SQL 側で計算する）
COL_SOURCE = "ファイル名"
COL_SOURCE_ROW = "元の行番号"  # 見出し行を 1 行目とした行番号
