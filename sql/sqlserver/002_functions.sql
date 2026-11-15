-- =====================================================================
-- sqlserver/002_functions.sql  月次推移・指標・ABC 分析（SQL Server / T-SQL 版）
-- 状態: 未実行（SQL Server の実行環境がないため、構文・動作とも確認していない）
--
-- SQLite 版は条件を w_cond_* 表に書いてビューで読むが、SQL Server は複数の利用者が同じ
-- データベースを使う前提になるため、条件を引数で受け取るインライン表値関数にしている。
-- 担当者・カテゴリ・地域は 1 つだけ指定でき、NULL は「すべて」。複数選択が必要な場合は
-- 表値パラメータ（ユーザー定義テーブル型）に置き換える。
-- 計算式は SQLite 版（../002_views.sql）と同じ。
-- =====================================================================
GO
CREATE OR ALTER FUNCTION dbo.fn_dim_line (@staff NVARCHAR(40), @category NVARCHAR(40), @region NVARCHAR(20))
RETURNS TABLE AS RETURN
SELECT l.*
FROM dbo.t_sales_line AS l
WHERE (@staff IS NULL OR l.staff = @staff)
  AND (@category IS NULL OR l.category = @category)
  AND (@region IS NULL OR l.region = @region);
GO
-- 月次推移（v_monthly_sales に相当）
CREATE OR ALTER FUNCTION dbo.fn_monthly_sales (
    @start_idx INT, @end_idx INT, @staff NVARCHAR(40), @category NVARCHAR(40), @region NVARCHAR(20))
RETURNS TABLE AS RETURN
WITH available AS (
    SELECT DISTINCT ym_idx FROM dbo.t_sales_line
), month_value AS (
    SELECT a.ym_idx,
           COALESCE(SUM(d.sales_amount), 0) AS sales,
           COALESCE(SUM(d.gross_profit), 0) AS profit
    FROM available AS a
    LEFT JOIN dbo.fn_dim_line(@staff, @category, @region) AS d ON d.ym_idx = a.ym_idx
    GROUP BY a.ym_idx
)
SELECT m.ym_idx,
       m.ym,
       cur.sales                                                          AS sales,
       cur.profit                                                         AS gross_profit,
       CASE WHEN cur.sales > 0 THEN cur.profit / cur.sales END            AS gross_margin,
       py.sales                                                           AS prev_year_sales,
       CASE WHEN py.sales > 0 THEN cur.sales / py.sales END               AS yoy,
       pm.sales                                                           AS prev_month_sales,
       CASE WHEN pm.sales > 0 THEN cur.sales / pm.sales END               AS mom
FROM dbo.m_month AS m
LEFT JOIN month_value AS cur ON cur.ym_idx = m.ym_idx
LEFT JOIN month_value AS py  ON py.ym_idx  = m.ym_idx - 12
LEFT JOIN month_value AS pm  ON pm.ym_idx  = m.ym_idx - 1
WHERE m.ym_idx BETWEEN @start_idx AND @end_idx;
GO
-- ABC 分析（得意先。v_abc_customer に相当）
CREATE OR ALTER FUNCTION dbo.fn_abc_customer (
    @start_idx INT, @end_idx INT, @staff NVARCHAR(40), @category NVARCHAR(40), @region NVARCHAR(20))
RETURNS TABLE AS RETURN
WITH agg AS (
    SELECT customer_code AS code, SUM(sales_amount) AS sales, SUM(gross_profit) AS profit
    FROM dbo.fn_dim_line(@staff, @category, @region)
    WHERE ym_idx BETWEEN @start_idx AND @end_idx
    GROUP BY customer_code
), ranked AS (
    SELECT agg.*,
           CASE WHEN SUM(sales) OVER () > 0 THEN sales / SUM(sales) OVER () END AS share,
           ROW_NUMBER() OVER (ORDER BY sales DESC, code) AS rank_no
    FROM agg
), cum AS (
    SELECT ranked.*,
           SUM(share) OVER (ORDER BY rank_no ROWS UNBOUNDED PRECEDING) AS cum_share,
           COALESCE(SUM(share) OVER (ORDER BY rank_no ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
               AS share_before
    FROM ranked
)
SELECT c.rank_no, c.code, m.customer_name AS name, c.sales, c.profit AS gross_profit,
       CASE WHEN c.sales > 0 THEN c.profit / c.sales END AS gross_margin,
       c.share, c.cum_share,
       CASE WHEN c.sales <= 0 OR c.share IS NULL THEN 'C'
            WHEN c.share_before < 0.70 THEN 'A'
            WHEN c.share_before < 0.90 THEN 'B'
            ELSE 'C' END AS abc_class
FROM cum AS c
JOIN dbo.m_customer AS m ON m.customer_code = c.code;
GO
