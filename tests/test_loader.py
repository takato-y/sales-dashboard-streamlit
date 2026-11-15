"""読み込み・検証・整形（FN-001・FN-002）のテスト。"""

from datetime import datetime

import pandas as pd
import pytest

from sales_dashboard import loader
from sales_dashboard import schema as s
from tests.helpers import row, to_csv_bytes, to_xlsx_bytes


def load(*files):
    return loader.load_files(list(files))


# ---- FN-001 ファイルの読み込み

def test_tc001_utf8_csv_is_loaded_and_typed():
    r = load(("a.csv", to_csv_bytes([row(qty=3, price=120, cost=80)])))
    assert len(r.data) == 1 and len(r.rejected) == 0
    d = r.data.iloc[0]
    assert d[s.COL_QTY] == 3 and d[s.COL_PRICE] == 120 and d[s.COL_COST] == 80
    assert d[s.COL_DATE] == pd.Timestamp("2025-01-06")


def test_tc002_cp932_csv_is_loaded():
    r = load(("sjis.csv", to_csv_bytes([row(cname="ＳＪＩＳ商店")], encoding="cp932")))
    assert r.data.iloc[0][s.COL_CUST_NAME] == "ＳＪＩＳ商店"


def test_tc003_xlsx_with_datetime_and_serial():
    rows = [row(slip="S1", day=datetime(2025, 1, 6)), row(slip="S2", day=45663)]
    r = load(("a.xlsx", to_xlsx_bytes(rows)))
    assert len(r.data) == 2, r.rejected
    assert set(r.data[s.COL_DATE].dt.strftime("%Y-%m-%d")) == {"2025-01-06"}


def test_tc004_multiple_files_are_combined_in_name_order():
    b = ("2025-02.csv", to_csv_bytes([row(slip="B", day="2025-02-03")]))
    a = ("2025-01.csv", to_csv_bytes([row(slip="A")]))
    r = load(b, a)
    assert r.files_read == ["2025-01.csv", "2025-02.csv"]
    assert list(r.data[s.COL_SLIP]) == ["A", "B"]


@pytest.mark.parametrize("name,content,reason", [
    ("a.txt", b"x", "対応していない形式"),
    ("a.csv", b"", "ファイルが空"),
    ("a.xlsx", b"not a zip", "Excel ファイルとして開けません"),
    ("a.csv", "伝票番号,売上日\nS1,2025-01-01\n".encode(), "必須の列がありません：行番号"),
])
def test_tc005_file_level_errors_do_not_stop_other_files(name, content, reason):
    ok = ("ok.csv", to_csv_bytes([row()]))
    r = load((name, content), ok)
    assert len(r.file_errors) == 1 and reason in r.file_errors[0].reason
    assert len(r.data) == 1  # ほかのファイルは読み込まれる


def test_tc006_undecodable_csv():
    bad = b"\x81\x7f,x\n1,2\n"  # UTF-8 としても CP932 としても不正なバイト列
    r = load(("bad.csv", bad))
    assert r.file_errors and "文字コード" in r.file_errors[0].reason


def test_tc007_extra_columns_and_column_order_are_ignored():
    header = list(reversed(s.REQUIRED_COLUMNS)) + ["備考"]
    rows = [list(reversed(row())) + ["メモ"]]
    r = load(("a.csv", to_csv_bytes(rows, header=header)))
    assert len(r.data) == 1 and "備考" not in r.data.columns


# ---- FN-002 検証・整形

def test_tc010_normalizes_fullwidth_and_currency():
    r = load(("a.csv", to_csv_bytes([row(slip="Ｓ１", qty="１２", price="¥1,280", cost="８９６円",
                                          day="2025/1/6", cname="  前後空白  ")])))
    d = r.data.iloc[0]
    assert d[s.COL_SLIP] == "S1" and d[s.COL_QTY] == 12 and d[s.COL_PRICE] == 1280 and d[s.COL_COST] == 896
    assert d[s.COL_CUST_NAME] == "前後空白"
    assert d[s.COL_DATE] == pd.Timestamp("2025-01-06")


def test_tc011_date_formats():
    rows = [row(slip=str(i), day=d) for i, d in enumerate(["2025-01-06", "2025/01/06", "20250106"])]
    r = load(("a.csv", to_csv_bytes(rows)))
    assert len(r.data) == 3


@pytest.mark.parametrize("override,reason", [
    (dict(day="2025-02-30"), "売上日を日付として読めません"),
    (dict(day="来週"), "売上日を日付として読めません"),
    (dict(day=""), "売上日が空です"),
    (dict(qty=""), "数量が空です"),
    (dict(qty="1.5"), "数量が整数ではありません"),
    (dict(qty="abc"), "数量が整数ではありません"),
    (dict(qty=0), "数量が0です"),
    (dict(price="千円"), "単価が数値ではありません"),
    (dict(price=-1), "単価がマイナスです"),
    (dict(cost=""), "原価単価が空です"),
    (dict(cname=""), "得意先名が空です"),
    (dict(staff="   "), "担当者が空です"),
    (dict(line=0), "行番号が1以上の整数ではありません"),
])
def test_tc012_row_level_errors(override, reason):
    r = load(("a.csv", to_csv_bytes([row(**override)])))
    assert len(r.data) == 0
    assert r.rejected.iloc[0]["理由"] == reason


def test_tc013_negative_quantity_is_return_and_accepted():
    r = load(("a.csv", to_csv_bytes([row(qty=-2, price=100, cost=70)])))
    assert r.data.iloc[0][s.COL_QTY] == -2  # 金額は SQL 側で計算（TC-045）


def test_tc014_multiple_reasons_are_joined_and_row_number_matches_file():
    rows = [row(slip="S1"), row(slip="S2", qty="", price="x", cname="")]
    r = load(("a.csv", to_csv_bytes(rows)))
    rej = r.rejected.iloc[0]
    assert rej[s.COL_SOURCE] == "a.csv" and rej[s.COL_SOURCE_ROW] == 3  # 見出し=1行目、2件目のデータ=3行目
    assert rej["理由"] == "得意先名が空です／数量が空です／単価が数値ではありません"


def test_tc015_duplicates_across_files_keep_first():
    a = ("2025-01.csv", to_csv_bytes([row(slip="S1", line=1), row(slip="S1", line=2)]))
    b = ("2025-01_再出力.csv", to_csv_bytes([row(slip="S1", line=2)]))
    r = load(b, a)
    assert len(r.data) == 2
    assert len(r.rejected) == 1 and r.rejected.iloc[0][s.COL_SOURCE] == "2025-01_再出力.csv"
    assert r.rejected.iloc[0]["理由"].startswith("明細の重複")


def test_tc016_invalid_row_does_not_shadow_valid_duplicate():
    rows = [row(slip="S1", qty=""), row(slip="S1", qty=5)]
    r = load(("a.csv", to_csv_bytes(rows)))
    assert len(r.data) == 1 and r.data.iloc[0][s.COL_QTY] == 5
    assert r.rejected.iloc[0]["理由"] == "数量が空です"


def test_tc017_blank_rows_are_skipped_and_counted():
    rows = [row(slip="S1"), [""] * 13, row(slip="S2")]
    r = load(("a.csv", to_csv_bytes(rows)))
    assert len(r.data) == 2 and r.blank_rows == 1 and len(r.rejected) == 0
    assert r.total_rows == 2


def test_tc018_error_sample_file():
    r = loader.load_paths(["samples/sales_errors_sample.csv"])
    assert len(r.rejected) == 7 and len(r.data) == 14
    # 数式に見える得意先名は読み込み時には変えない（無害化は出力時だけ）
    assert r.data[s.COL_CUST_NAME].str.startswith("=HYPERLINK").sum() == 1
