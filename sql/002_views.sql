-- =====================================================================
-- 002_views.sql  指標・月次推移・ABC 分析・内訳のビュー（SQLite）
-- 指標の定義: docs/03_基本設計.md「指標の定義」。ABC の区分: docs/adr/0002
-- 割合は分母が 0 以下のとき NULL（画面では「—」）にする。
-- =====================================================================

-- データにある月（絞り込みに関係なく、読み込んだ明細に 1 行でもある月）
CREATE VIEW v_available_month AS
SELECT DISTINCT ym_idx, ym FROM t_sales_line;

-- 期間の条件。未指定ならデータの最初・最後の月
CREATE VIEW v_period AS
SELECT COALESCE(c.start_idx, (SELECT MIN(ym_idx) FROM t_sales_line)) AS start_idx,
       COALESCE(c.end_idx,   (SELECT MAX(ym_idx) FROM t_sales_line)) AS end_idx
FROM w_cond_period AS c
WHERE c.id = 1;

-- 担当者・カテゴリ・地域で絞り込んだ明細（期間は問わない。前年同月比・前月比の計算に使う）
CREATE VIEW v_dim_line AS
SELECT l.*
FROM t_sales_line AS l
WHERE (NOT EXISTS (SELECT 1 FROM w_cond_staff)    OR l.staff    IN (SELECT staff    FROM w_cond_staff))
  AND (NOT EXISTS (SELECT 1 FROM w_cond_category) OR l.category IN (SELECT category FROM w_cond_category))
  AND (NOT EXISTS (SELECT 1 FROM w_cond_region)   OR l.region   IN (SELECT region   FROM w_cond_region));

-- すべての条件で絞り込んだ明細
CREATE VIEW v_filtered_line AS
SELECT d.*
FROM v_dim_line AS d
JOIN v_period AS p ON d.ym_idx BETWEEN p.start_idx AND p.end_idx;

-- 期間内の全月（データの欠けた月も 1 行にする）
CREATE VIEW v_month_seq AS
WITH RECURSIVE seq (ym_idx) AS (
    SELECT start_idx FROM v_period WHERE start_idx IS NOT NULL
    UNION ALL
    SELECT seq.ym_idx + 1 FROM seq, v_period WHERE seq.ym_idx < v_period.end_idx
)
SELECT ym_idx, printf('%04d-%02d', ym_idx / 12, ym_idx % 12 + 1) AS ym FROM seq;

-- データにある月ごとの、絞り込み後の売上・粗利（データはあるが該当がない月は 0）
CREATE VIEW v_month_value AS
SELECT a.ym_idx,
       COALESCE(SUM(d.sales_amount), 0) AS sales,
       COALESCE(SUM(d.gross_profit), 0) AS profit
FROM v_available_month AS a
LEFT JOIN v_dim_line AS d ON d.ym_idx = a.ym_idx
GROUP BY a.ym_idx;

-- 月次推移：売上・粗利・粗利率・前年同月売上・前年同月比・前月売上・前月比
CREATE VIEW v_monthly_sales AS
SELECT s.ym_idx,
       s.ym,
       cur.sales                                                        AS sales,
       cur.profit                                                       AS gross_profit,
       CASE WHEN cur.sales > 0 THEN cur.profit / cur.sales END          AS gross_margin,
       py.sales                                                         AS prev_year_sales,
       CASE WHEN py.sales > 0 THEN cur.sales / py.sales END             AS yoy,
       pm.sales                                                         AS prev_month_sales,
       CASE WHEN pm.sales > 0 THEN cur.sales / pm.sales END             AS mom
FROM v_month_seq AS s
LEFT JOIN v_month_value AS cur ON cur.ym_idx = s.ym_idx
LEFT JOIN v_month_value AS py  ON py.ym_idx  = s.ym_idx - 12
LEFT JOIN v_month_value AS pm  ON pm.ym_idx  = s.ym_idx - 1;

-- 期間の指標（1 行）。前年同月比・前月比は期間の最終月について求める
CREATE VIEW v_kpi AS
SELECT p.start_idx,
       p.end_idx,
       (SELECT COUNT(*) FROM v_filtered_line)                            AS row_count,
       (SELECT COALESCE(SUM(sales_amount), 0) FROM v_filtered_line)      AS sales,
       (SELECT COALESCE(SUM(gross_profit), 0) FROM v_filtered_line)      AS gross_profit,
       (SELECT CASE WHEN SUM(sales_amount) > 0 THEN SUM(gross_profit) / SUM(sales_amount) END
          FROM v_filtered_line)                                          AS gross_margin,
       m.ym                                                              AS target_ym,
       m.sales                                                           AS month_sales,
       m.prev_month_sales,
       m.mom,
       m.prev_year_sales,
       m.yoy
FROM v_period AS p
LEFT JOIN v_monthly_sales AS m ON m.ym_idx = p.end_idx;

-- ABC 分析（得意先）。前までの累積構成比が 70% 未満は A、90% 未満は B、それ以外と売上 0 以下は C
CREATE VIEW v_abc_customer AS
WITH agg AS (
    SELECT customer_code AS code, SUM(sales_amount) AS sales, SUM(gross_profit) AS profit
    FROM v_filtered_line GROUP BY customer_code
), ranked AS (
    SELECT agg.*,
           CASE WHEN t.total > 0 THEN agg.sales / t.total END AS share,
           ROW_NUMBER() OVER (ORDER BY agg.sales DESC, agg.code) AS rank_no
    FROM agg, (SELECT SUM(sales) AS total FROM agg) AS t
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
JOIN m_customer AS m ON m.customer_code = c.code;

-- ABC 分析（商品）。区分の決め方は得意先と同じ
CREATE VIEW v_abc_product AS
WITH agg AS (
    SELECT product_code AS code, SUM(sales_amount) AS sales, SUM(gross_profit) AS profit
    FROM v_filtered_line GROUP BY product_code
), ranked AS (
    SELECT agg.*,
           CASE WHEN t.total > 0 THEN agg.sales / t.total END AS share,
           ROW_NUMBER() OVER (ORDER BY agg.sales DESC, agg.code) AS rank_no
    FROM agg, (SELECT SUM(sales) AS total FROM agg) AS t
), cum AS (
    SELECT ranked.*,
           SUM(share) OVER (ORDER BY rank_no ROWS UNBOUNDED PRECEDING) AS cum_share,
           COALESCE(SUM(share) OVER (ORDER BY rank_no ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
               AS share_before
    FROM ranked
)
SELECT c.rank_no, c.code, m.product_name AS name, c.sales, c.profit AS gross_profit,
       CASE WHEN c.sales > 0 THEN c.profit / c.sales END AS gross_margin,
       c.share, c.cum_share,
       CASE WHEN c.sales <= 0 OR c.share IS NULL THEN 'C'
            WHEN c.share_before < 0.70 THEN 'A'
            WHEN c.share_before < 0.90 THEN 'B'
            ELSE 'C' END AS abc_class
FROM cum AS c
JOIN m_product AS m ON m.product_code = c.code;

-- 内訳（地域・担当者・商品カテゴリ）。dimension 列に区分名が入る
CREATE VIEW v_breakdown AS
WITH agg AS (
    SELECT '地域' AS dimension, region AS item, SUM(sales_amount) AS sales, SUM(gross_profit) AS profit,
           COUNT(*) AS row_count
    FROM v_filtered_line GROUP BY region
    UNION ALL
    SELECT '担当者', staff, SUM(sales_amount), SUM(gross_profit), COUNT(*) FROM v_filtered_line GROUP BY staff
    UNION ALL
    SELECT '商品カテゴリ', category, SUM(sales_amount), SUM(gross_profit), COUNT(*)
    FROM v_filtered_line GROUP BY category
)
SELECT dimension, item, sales, profit AS gross_profit,
       CASE WHEN sales > 0 THEN profit / sales END AS gross_margin,
       CASE WHEN SUM(sales) OVER (PARTITION BY dimension) > 0
            THEN sales / SUM(sales) OVER (PARTITION BY dimension) END AS share,
       row_count
FROM agg;

-- 絞り込みの選択肢（読み込んだ明細にある値）
CREATE VIEW v_filter_option AS
SELECT DISTINCT '担当者' AS dimension, staff AS item FROM t_sales_line
UNION SELECT DISTINCT '商品カテゴリ', category FROM t_sales_line
UNION SELECT DISTINCT '地域', region FROM t_sales_line;
