-- =====================================================================
-- sqlserver/001_schema.sql  売上分析の表（SQL Server / T-SQL 版）
-- 状態: 未実行（SQL Server の実行環境がないため、構文・動作とも確認していない）
-- SQLite 版（../001_schema.sql）との違いは ../README.md の「SQL Server へ移すとき」を参照。
-- =====================================================================

CREATE TABLE dbo.t_import_file (
    file_id        INT            NOT NULL PRIMARY KEY,
    file_name      NVARCHAR(260)  NOT NULL UNIQUE,
    accepted_rows  INT            NOT NULL DEFAULT 0,
    rejected_rows  INT            NOT NULL DEFAULT 0
);

CREATE TABLE dbo.m_customer (
    customer_code  NVARCHAR(20)   NOT NULL PRIMARY KEY,
    customer_name  NVARCHAR(100)  NOT NULL
);

CREATE TABLE dbo.m_product (
    product_code   NVARCHAR(20)   NOT NULL PRIMARY KEY,
    product_name   NVARCHAR(100)  NOT NULL
);

-- 月の一覧（期間内の全月を出すために使う。SQLite 版の再帰 CTE の代わり）
CREATE TABLE dbo.m_month (
    ym_idx  INT         NOT NULL PRIMARY KEY,   -- 年×12＋月−1
    ym      CHAR(7)     NOT NULL                -- YYYY-MM
);

CREATE TABLE dbo.t_sales_line (
    slip_no        NVARCHAR(20)   NOT NULL,
    line_no        INT            NOT NULL,
    sales_date     DATE           NOT NULL,
    ym             AS (CONVERT(CHAR(7), sales_date, 126)) PERSISTED,
    ym_idx         AS (YEAR(sales_date) * 12 + MONTH(sales_date) - 1) PERSISTED,
    customer_code  NVARCHAR(20)   NOT NULL REFERENCES dbo.m_customer (customer_code),
    region         NVARCHAR(20)   NOT NULL,
    staff          NVARCHAR(40)   NOT NULL,
    product_code   NVARCHAR(20)   NOT NULL REFERENCES dbo.m_product (product_code),
    category       NVARCHAR(40)   NOT NULL,
    quantity       INT            NOT NULL CHECK (quantity <> 0),
    unit_price     DECIMAL(18, 2) NOT NULL CHECK (unit_price >= 0),
    unit_cost      DECIMAL(18, 2) NOT NULL CHECK (unit_cost >= 0),
    sales_amount   AS (quantity * unit_price) PERSISTED,
    cost_amount    AS (quantity * unit_cost) PERSISTED,
    gross_profit   AS (quantity * unit_price - quantity * unit_cost) PERSISTED,
    file_id        INT            NOT NULL REFERENCES dbo.t_import_file (file_id),
    source_row     INT            NOT NULL,
    CONSTRAINT pk_t_sales_line PRIMARY KEY (slip_no, line_no)
);
CREATE INDEX ix_sales_line_ym ON dbo.t_sales_line (ym_idx) INCLUDE (sales_amount, gross_profit, staff, category, region);
