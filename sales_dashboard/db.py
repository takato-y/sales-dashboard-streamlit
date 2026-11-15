"""SQL による集計層（SQLite）。

検証を通った明細を SQLite に入れ、指標・月次推移・ABC 分析・内訳は sql/ のビューで計算する。
Python 側は「条件を表に書く → ビューを SELECT する」だけを行い、集計の式は持たない。

sql/ の番号付きファイル（001_schema.sql, 002_views.sql, …）は番号順に一度だけ適用し、
適用した番号を schema_version 表に記録する。既定はメモリ上のデータベース（ディスクに残さない）。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import schema as s
from .filters import FilterCondition
from .loader import LoadResult

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
_VERSIONED = re.compile(r"^(\d{3})_.+\.sql$")

ABC_COLUMNS = ["順位", "コード", "名称", "売上", "粗利", "粗利率", "構成比", "累積構成比", "区分"]
BREAKDOWN_COLUMNS = ["売上", "粗利", "粗利率", "構成比", "明細数"]
TREND_COLUMNS = ["年月", "売上", "粗利", "粗利率", "前年同月売上", "前年同月比"]
DIMENSIONS = {"担当者": ("w_cond_staff", "staff"),
              "商品カテゴリ": ("w_cond_category", "category"),
              "地域": ("w_cond_region", "region")}


@dataclass
class KpiSummary:
    """v_kpi の 1 行。割合は算出できないとき None。"""

    period_start: str | None
    period_end: str | None
    rows: int
    sales: float
    profit: float
    margin: float | None
    target_month: str | None        # 前年同月比・前月比の対象月（期間の最終月）
    month_sales: float | None
    prev_month_sales: float | None  # データにその月がなければ None（0 とは区別する）
    prev_year_sales: float | None
    mom: float | None               # 前月比 ＝ 対象月の売上 ÷ 前月の売上
    yoy: float | None               # 前年同月比 ＝ 対象月の売上 ÷ 前年同月の売上


def period_to_idx(p: pd.Period | None) -> int | None:
    """年月を「年×12＋月−1」の整数にする（SQL の ym_idx と同じ）。"""
    return None if p is None else p.year * 12 + p.month - 1


def idx_to_ym(i: int | None) -> str | None:
    return None if i is None else f"{i // 12:04d}-{i % 12 + 1:02d}"


def migration_files(sql_dir: Path = SQL_DIR) -> list[tuple[int, Path]]:
    """番号付きの SQL ファイル（NNN_名前.sql）を番号順に返す。"""
    files = []
    for p in sql_dir.iterdir():
        m = _VERSIONED.match(p.name)
        if m:
            files.append((int(m.group(1)), p))
    return sorted(files)


class SalesDB:
    """1 つの画面（Streamlit のセッション）につき 1 つ作る。"""

    def __init__(self, path: str = ":memory:", sql_dir: Path = SQL_DIR):
        # Streamlit は同じセッションの再実行を別のスレッドで行うことがあるため check_same_thread=False
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.sql_dir = sql_dir
        self.migrate()

    # ------------------------------------------------------------ スキーマ

    def migrate(self) -> list[int]:
        """未適用の番号付き SQL を番号順に適用し、適用した番号を返す。"""
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                  "version INTEGER PRIMARY KEY, file_name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        done = {r[0] for r in c.execute("SELECT version FROM schema_version")}
        applied = []
        for version, path in migration_files(self.sql_dir):
            if version in done:
                continue
            self._run_script(path.read_text(encoding="utf-8"))
            with c:
                c.execute("INSERT INTO schema_version VALUES (?, ?, ?)",
                          (version, path.name, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            applied.append(version)
        return applied

    def schema_versions(self) -> list[int]:
        return [r[0] for r in self.conn.execute("SELECT version FROM schema_version ORDER BY version")]

    # ------------------------------------------------------------ 取込

    def load(self, result: LoadResult) -> None:
        """検証を通った明細を一時置き場に入れ、load_sales.sql で本表へ移す（全件入れ替え）。"""
        c = self.conn
        data = result.data
        rejected = result.rejected
        rejected_by_file = rejected[s.COL_SOURCE].value_counts().to_dict() if len(rejected) else {}
        accepted_by_file = data[s.COL_SOURCE].value_counts().to_dict() if len(data) else {}
        file_ids = {name: i for i, name in enumerate(result.files_read, start=1)}
        with c:
            c.execute("DELETE FROM t_sales_line")
            c.execute("DELETE FROM t_import_file")
            c.execute("DELETE FROM stg_sales_line")
            c.executemany(
                "INSERT INTO t_import_file (file_id, file_name, accepted_rows, rejected_rows) VALUES (?, ?, ?, ?)",
                [(i, n, int(accepted_by_file.get(n, 0)), int(rejected_by_file.get(n, 0)))
                 for n, i in file_ids.items()])
            if len(data):
                stg = pd.DataFrame({
                    "file_id": data[s.COL_SOURCE].map(file_ids).astype("int64"),
                    "source_row": data[s.COL_SOURCE_ROW].astype("int64"),
                    "slip_no": data[s.COL_SLIP], "line_no": data[s.COL_LINE].astype("int64"),
                    "sales_date": data[s.COL_DATE].dt.strftime("%Y-%m-%d"),
                    "customer_code": data[s.COL_CUST_CODE], "customer_name": data[s.COL_CUST_NAME],
                    "region": data[s.COL_REGION], "staff": data[s.COL_STAFF],
                    "product_code": data[s.COL_PROD_CODE], "product_name": data[s.COL_PROD_NAME],
                    "category": data[s.COL_CATEGORY], "quantity": data[s.COL_QTY].astype("int64"),
                    "unit_price": data[s.COL_PRICE].astype("float64"),
                    "unit_cost": data[s.COL_COST].astype("float64"),
                })
                cols = ", ".join(stg.columns)
                marks = ", ".join("?" * len(stg.columns))
                rows = ((i, *r) for i, r in enumerate(stg.itertuples(index=False, name=None), start=1))
                c.executemany(f"INSERT INTO stg_sales_line (load_seq, {cols}) VALUES (?, {marks})", rows)
        procedure = (self.sql_dir / "procedures" / "load_sales.sql").read_text(encoding="utf-8")
        self._run_script(procedure)

    def _run_script(self, script: str) -> None:
        """SQL ファイルを 1 つのトランザクションで実行する。失敗したら元に戻して例外を送出する。"""
        try:
            self.conn.executescript("BEGIN;" + script + "\nCOMMIT;")
        except sqlite3.Error:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    # ------------------------------------------------------------ 条件

    def set_condition(self, cond: FilterCondition) -> None:
        """絞り込み条件を w_cond_* 表に書く。以降の SELECT はこの条件で計算される。"""
        c = self.conn
        values = {"担当者": cond.staff, "商品カテゴリ": cond.categories, "地域": cond.regions}
        with c:
            c.execute("UPDATE w_cond_period SET start_idx = ?, end_idx = ? WHERE id = 1",
                      (period_to_idx(cond.start), period_to_idx(cond.end)))
            for dim, (table, col) in DIMENSIONS.items():  # 表名・列名は固定の対応表からのみ取る
                c.execute(f"DELETE FROM {table}")
                c.executemany(f"INSERT INTO {table} ({col}) VALUES (?)", [(v,) for v in values[dim]])

    # ------------------------------------------------------------ 参照

    def query(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.conn, params=params)

    def months(self) -> list[str]:
        """データの最初の月から最後の月までの全月（YYYY-MM）。"""
        lo, hi = self.conn.execute("SELECT MIN(ym_idx), MAX(ym_idx) FROM t_sales_line").fetchone()
        return [] if lo is None else [idx_to_ym(i) for i in range(lo, hi + 1)]

    def options(self, dimension: str) -> list[str]:
        """絞り込みの選択肢。dimension は「担当者」「商品カテゴリ」「地域」。"""
        rows = self.conn.execute("SELECT item FROM v_filter_option WHERE dimension = ? ORDER BY item",
                                 (dimension,)).fetchall()
        return [r[0] for r in rows]

    def kpis(self) -> KpiSummary:
        r = self.conn.execute(
            "SELECT start_idx, end_idx, row_count, sales, gross_profit, gross_margin, target_ym, "
            "month_sales, prev_month_sales, mom, prev_year_sales, yoy FROM v_kpi").fetchone()
        if r is None:  # w_cond_period の行が失われた場合のみ
            raise RuntimeError("v_kpi が行を返しませんでした")
        return KpiSummary(
            period_start=idx_to_ym(r[0]), period_end=idx_to_ym(r[1]), rows=r[2], sales=r[3], profit=r[4],
            margin=r[5], target_month=r[6], month_sales=r[7], prev_month_sales=r[8], mom=r[9],
            prev_year_sales=r[10], yoy=r[11])

    def monthly_trend(self) -> pd.DataFrame:
        df = self.query("SELECT ym, sales, gross_profit, gross_margin, prev_year_sales, yoy "
                        "FROM v_monthly_sales ORDER BY ym_idx")
        df.columns = TREND_COLUMNS
        return df.astype({c: "float64" for c in TREND_COLUMNS[1:]})

    def abc(self, kind: str) -> pd.DataFrame:
        """kind は「得意先」または「商品」。"""
        view = {"得意先": "v_abc_customer", "商品": "v_abc_product"}[kind]
        df = self.query(f"SELECT rank_no, code, name, sales, gross_profit, gross_margin, share, cum_share, "
                        f"abc_class FROM {view} ORDER BY rank_no")
        df.columns = ABC_COLUMNS
        return df.astype({c: "float64" for c in ("売上", "粗利", "粗利率", "構成比", "累積構成比")})

    def breakdown(self, dimension: str) -> pd.DataFrame:
        """dimension は「地域」「担当者」「商品カテゴリ」。売上の多い順。"""
        df = self.query("SELECT item, sales, gross_profit, gross_margin, share, row_count FROM v_breakdown "
                        "WHERE dimension = ? ORDER BY sales DESC, item", (dimension,))
        df.columns = [dimension] + BREAKDOWN_COLUMNS
        return df.astype({c: "float64" for c in ("売上", "粗利", "粗利率", "構成比")})

    def import_files(self) -> pd.DataFrame:
        df = self.query("SELECT file_name, accepted_rows, rejected_rows FROM t_import_file ORDER BY file_id")
        df.columns = ["ファイル名", "受け付けた行", "除外した行"]
        return df


def abc_summary(abc: pd.DataFrame) -> pd.DataFrame:
    """ABC の区分ごとの件数・売上・構成比（v_abc_* の結果を数えるだけ）。"""
    total = float(abc["売上"].sum()) if len(abc) else 0.0
    rows = []
    for k in ("A", "B", "C"):
        part = abc[abc["区分"] == k]
        sales = float(part["売上"].sum())
        rows.append([k, len(part), sales, sales / total if total > 0 else float("nan")])
    return pd.DataFrame(rows, columns=["区分", "件数", "売上", "構成比"])
