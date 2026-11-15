"""売上明細ファイルの読み込み・検証・整形（REQ-001・REQ-002 / FN-001・FN-002）。

処理の流れは docs/03_詳細設計.md の「読込・検証の流れ」を参照。
ファイル単位の誤り（形式・文字コード・必須列）はそのファイルを読まずに記録し、
行単位の誤りはその行を除外して理由を残す。どちらの場合も処理は止めない。
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePath
from typing import Iterable

import numpy as np
import pandas as pd

from . import schema as s

SUPPORTED_EXTENSIONS = (".csv", ".xlsx")
CSV_ENCODINGS = ("utf-8-sig", "cp932")
REASON_SEP = "／"
EXCEL_EPOCH = pd.Timestamp("1899-12-30")  # Excel の日付シリアル値の起点


@dataclass
class FileError:
    """ファイル単位の誤り（ERR-001〜ERR-005）。"""

    file: str
    reason: str


@dataclass
class LoadResult:
    """読み込み結果。data は集計に使う明細、rejected は除外した行。"""

    data: pd.DataFrame
    rejected: pd.DataFrame
    file_errors: list[FileError] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    blank_rows: int = 0

    @property
    def total_rows(self) -> int:
        """空行を除いて読んだ行数（受け付けた行＋除外した行）。"""
        return len(self.data) + len(self.rejected)


class FileLoadError(Exception):
    """1 ファイルを読めなかったことを表す（理由は利用者向けの文言）。"""


# ---------------------------------------------------------------- ファイルの読み込み

def _cell_to_text(v) -> str:
    """Excel から読んだ値を文字列にそろえる。整数の float は小数点を付けない。"""
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d") if not pd.isna(v) else ""
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def read_table(name: str, content: bytes) -> pd.DataFrame:
    """1 ファイルを読み、すべての値を文字列にした DataFrame を返す。

    読めない場合は FileLoadError（理由は画面にそのまま出す文言）を送出する。
    """
    ext = PurePath(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileLoadError("対応していない形式です（.csv または .xlsx を選んでください）")
    if ext == ".csv":
        for enc in CSV_ENCODINGS:
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
            except pd.errors.EmptyDataError:
                raise FileLoadError("ファイルが空です") from None
            except pd.errors.ParserError:
                raise FileLoadError("CSV として読めません（列の数がそろっていない行があります）") from None
        else:
            raise FileLoadError("文字コードを判定できません（UTF-8 または Shift_JIS で保存してください）")
    else:
        try:
            df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=object, engine="openpyxl")
        except (zipfile.BadZipFile, ValueError, KeyError, OSError):
            raise FileLoadError("Excel ファイルとして開けません") from None
        df = df.apply(lambda col: col.map(_cell_to_text)).astype(str) if len(df) else df.astype(str)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in s.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise FileLoadError("必須の列がありません：" + "、".join(missing))
    return df[s.REQUIRED_COLUMNS].copy()


# ---------------------------------------------------------------- 整形

def _strip(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def _nfkc(series: pd.Series) -> pd.Series:
    """全角英数・記号を半角にそろえる（Unicode NFKC 正規化）。"""
    return series.astype(str).str.normalize("NFKC").str.strip()


def _parse_number(series: pd.Series) -> pd.Series:
    """「１，２８０円」「¥1,280」のような表記を数値にする。読めない値は NaN。"""
    text = _nfkc(series).str.replace(r"[,¥円\s]", "", regex=True)
    return pd.to_numeric(text, errors="coerce")


def _parse_date(series: pd.Series) -> pd.Series:
    """複数の日付書式と Excel のシリアル値を受け付ける。読めない値は NaT。"""
    text = _nfkc(series)
    result = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    for fmt in ("%Y/%m/%d", "%Y%m%d"):
        todo = result.isna() & (text != "")
        if not todo.any():
            break
        if fmt == "%Y%m%d":
            todo &= text.str.fullmatch(r"\d{8}")
        result = result.where(~todo, pd.to_datetime(text.where(todo), format=fmt, errors="coerce"))
    # Excel の日付シリアル値（例：45663 = 2025-01-06）。1982〜2173 年相当の範囲だけを受け付ける
    todo = result.isna() & text.str.fullmatch(r"\d{5}")
    if todo.any():
        serial = pd.to_numeric(text.where(todo), errors="coerce")
        serial = serial.where((serial >= 30000) & (serial <= 99999))
        result = result.where(~todo, EXCEL_EPOCH + pd.to_timedelta(serial, unit="D"))
    return result


# ---------------------------------------------------------------- 検証

def _validate(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """整形した値と、行ごとの誤りの理由（誤りがなければ空文字）を返す。"""
    clean = pd.DataFrame(index=raw.index)
    reasons = pd.Series("", index=raw.index, dtype=object)

    def add(mask: pd.Series, message: str) -> None:
        nonlocal reasons
        reasons = reasons.where(~mask, reasons + REASON_SEP + message)

    for col in s.CODE_COLUMNS:
        clean[col] = _nfkc(raw[col])
    for col in s.TEXT_COLUMNS:
        clean[col] = _strip(raw[col])
    for col in s.CODE_COLUMNS + s.TEXT_COLUMNS:
        add(clean[col] == "", f"{col}が空です")

    line = _parse_number(raw[s.COL_LINE])
    line_text = _nfkc(raw[s.COL_LINE])
    add(line_text == "", "行番号が空です")
    add((line_text != "") & ~((line >= 1) & (line % 1 == 0)), "行番号が1以上の整数ではありません")
    clean[s.COL_LINE] = line

    date_text = _nfkc(raw[s.COL_DATE])
    parsed = _parse_date(raw[s.COL_DATE])
    add(date_text == "", "売上日が空です")
    add((date_text != "") & parsed.isna(), "売上日を日付として読めません")
    clean[s.COL_DATE] = parsed

    qty_text = _nfkc(raw[s.COL_QTY])
    qty = _parse_number(raw[s.COL_QTY])
    add(qty_text == "", "数量が空です")
    add((qty_text != "") & ~(qty % 1 == 0), "数量が整数ではありません")
    add(qty == 0, "数量が0です")
    clean[s.COL_QTY] = qty

    for col in (s.COL_PRICE, s.COL_COST):
        text = _nfkc(raw[col])
        value = _parse_number(raw[col])
        add(text == "", f"{col}が空です")
        add((text != "") & value.isna(), f"{col}が数値ではありません")
        add(value < 0, f"{col}がマイナスです")
        clean[col] = value

    reasons = reasons.str.removeprefix(REASON_SEP)
    return clean, reasons


# ---------------------------------------------------------------- 全体

def _empty_data() -> pd.DataFrame:
    cols = s.REQUIRED_COLUMNS + [s.COL_SALES, s.COL_COST_AMOUNT, s.COL_PROFIT, s.COL_MONTH,
                                 s.COL_SOURCE, s.COL_SOURCE_ROW]
    return pd.DataFrame(columns=cols)


def _empty_rejected() -> pd.DataFrame:
    return pd.DataFrame(columns=[s.COL_SOURCE, s.COL_SOURCE_ROW, "理由"] + s.REQUIRED_COLUMNS)


def load_files(sources: Iterable[tuple[str, bytes]]) -> LoadResult:
    """複数のファイル（名前と中身）を読み、検証・整形した結果を返す。

    ファイルは名前の昇順で処理する。伝票番号と行番号の組が同じ明細は、
    先に読んだもの（名前の昇順・ファイル内の上から）を残し、後のものを除外する。
    """
    file_errors: list[FileError] = []
    files_read: list[str] = []
    frames: list[pd.DataFrame] = []
    for name, content in sorted(sources, key=lambda x: x[0]):
        try:
            raw = read_table(name, content)
        except FileLoadError as e:
            file_errors.append(FileError(name, str(e)))
            continue
        files_read.append(name)
        raw[s.COL_SOURCE] = name
        raw[s.COL_SOURCE_ROW] = np.arange(2, len(raw) + 2)  # 見出し行を 1 行目とする
        frames.append(raw)

    if not frames:
        return LoadResult(_empty_data(), _empty_rejected(), file_errors, files_read, 0)

    raw = pd.concat(frames, ignore_index=True)
    blank = (raw[s.REQUIRED_COLUMNS].apply(lambda c: c.astype(str).str.strip()) == "").all(axis=1)
    blank_rows = int(blank.sum())
    raw = raw[~blank]

    clean, reasons = _validate(raw)
    valid = reasons == ""
    # 明細の重複は、検証を通った行どうしで判定する（誤りのある行が正しい行を押し出さないように）
    dup = pd.Series(False, index=raw.index)
    dup[valid] = clean.loc[valid].duplicated([s.COL_SLIP, s.COL_LINE], keep="first")
    reasons = reasons.where(~dup, "明細の重複（同じ伝票番号・行番号の明細を先に読み込み済み）")
    valid &= ~dup

    rejected = raw.loc[~valid, [s.COL_SOURCE, s.COL_SOURCE_ROW] + s.REQUIRED_COLUMNS].copy()
    rejected.insert(2, "理由", reasons[~valid])
    rejected = rejected.reset_index(drop=True)

    data = clean.loc[valid, s.REQUIRED_COLUMNS].copy()
    data[s.COL_LINE] = data[s.COL_LINE].astype("int64")
    data[s.COL_QTY] = data[s.COL_QTY].astype("int64")
    data[s.COL_PRICE] = data[s.COL_PRICE].astype("float64")
    data[s.COL_COST] = data[s.COL_COST].astype("float64")
    data[s.COL_SALES] = data[s.COL_QTY] * data[s.COL_PRICE]
    data[s.COL_COST_AMOUNT] = data[s.COL_QTY] * data[s.COL_COST]
    data[s.COL_PROFIT] = data[s.COL_SALES] - data[s.COL_COST_AMOUNT]
    data[s.COL_MONTH] = data[s.COL_DATE].dt.to_period("M")
    data[s.COL_SOURCE] = raw.loc[valid, s.COL_SOURCE]
    data[s.COL_SOURCE_ROW] = raw.loc[valid, s.COL_SOURCE_ROW]
    data = data.reset_index(drop=True)
    return LoadResult(data, rejected, file_errors, files_read, blank_rows)


def load_paths(paths: Iterable[str]) -> LoadResult:
    """ローカルのファイルパスから読み込む（スクリプト・テスト用）。"""
    sources = []
    for p in paths:
        with open(p, "rb") as f:
            sources.append((PurePath(p).name, f.read()))
    return load_files(sources)
