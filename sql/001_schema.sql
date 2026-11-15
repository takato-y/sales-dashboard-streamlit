-- =====================================================================
-- 001_schema.sql  売上分析の表（SQLite）
-- 対応する設計書: docs/05_テーブル定義書.md
-- このファイルは一度適用したら書き換えない。変更は 003_*.sql のように新しい番号のファイルで行う。
-- =====================================================================

-- 取込ファイル（1 回の読み込みで受け付けたファイル）
CREATE TABLE t_import_file (
    file_id        INTEGER PRIMARY KEY,
    file_name      TEXT    NOT NULL UNIQUE,
    accepted_rows  INTEGER NOT NULL DEFAULT 0,
    rejected_rows  INTEGER NOT NULL DEFAULT 0
);

-- 得意先（名称は読み込んだ明細のうち最も新しい売上日のもの）
CREATE TABLE m_customer (
    customer_code  TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL
);

-- 商品（名称は読み込んだ明細のうち最も新しい売上日のもの）
CREATE TABLE m_product (
    product_code   TEXT PRIMARY KEY,
    product_name   TEXT NOT NULL
);

-- 取込用の一時置き場。Python が検証を通った明細だけを入れる。読み込みのたびに空にする
CREATE TABLE stg_sales_line (
    load_seq       INTEGER PRIMARY KEY,   -- 読み込んだ順（ファイル名の昇順・ファイル内の上から）
    file_id        INTEGER NOT NULL,
    source_row     INTEGER NOT NULL,
    slip_no        TEXT    NOT NULL,
    line_no        INTEGER NOT NULL,
    sales_date     TEXT    NOT NULL,      -- YYYY-MM-DD
    customer_code  TEXT    NOT NULL,
    customer_name  TEXT    NOT NULL,
    region         TEXT    NOT NULL,
    staff          TEXT    NOT NULL,
    product_code   TEXT    NOT NULL,
    product_name   TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    quantity       INTEGER NOT NULL,
    unit_price     REAL    NOT NULL,
    unit_cost      REAL    NOT NULL
);

-- 売上明細（集計の対象）。金額は取込時に SQL で計算する
CREATE TABLE t_sales_line (
    slip_no        TEXT    NOT NULL,
    line_no        INTEGER NOT NULL,
    sales_date     TEXT    NOT NULL,
    ym             TEXT    NOT NULL,      -- YYYY-MM
    ym_idx         INTEGER NOT NULL,      -- 年×12＋月−1（月の足し引きを整数で行うため）
    customer_code  TEXT    NOT NULL REFERENCES m_customer (customer_code),
    region         TEXT    NOT NULL,
    staff          TEXT    NOT NULL,
    product_code   TEXT    NOT NULL REFERENCES m_product (product_code),
    category       TEXT    NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity <> 0),
    unit_price     REAL    NOT NULL CHECK (unit_price >= 0),
    unit_cost      REAL    NOT NULL CHECK (unit_cost >= 0),
    sales_amount   REAL    NOT NULL,      -- 数量×単価
    cost_amount    REAL    NOT NULL,      -- 数量×原価単価
    gross_profit   REAL    NOT NULL,      -- 売上金額−原価金額
    file_id        INTEGER NOT NULL REFERENCES t_import_file (file_id),
    source_row     INTEGER NOT NULL,
    PRIMARY KEY (slip_no, line_no)
);
CREATE INDEX ix_sales_line_ym ON t_sales_line (ym_idx);
CREATE INDEX ix_sales_line_customer ON t_sales_line (customer_code);
CREATE INDEX ix_sales_line_product ON t_sales_line (product_code);

-- 絞り込み条件。画面の操作ごとに Python が書き換え、ビューはこれを参照する。
-- 期間は 1 行だけ持つ。担当者・カテゴリ・地域は行がなければ「すべて」
CREATE TABLE w_cond_period (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    start_idx  INTEGER,
    end_idx    INTEGER
);
INSERT INTO w_cond_period (id, start_idx, end_idx) VALUES (1, NULL, NULL);
CREATE TABLE w_cond_staff    (staff    TEXT PRIMARY KEY);
CREATE TABLE w_cond_category (category TEXT PRIMARY KEY);
CREATE TABLE w_cond_region   (region   TEXT PRIMARY KEY);
