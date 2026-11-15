-- =====================================================================
-- load_sales.sql  取込用の一時置き場（stg_sales_line）から本表へ移す
-- 読み込みのたびに全件を入れ替える。Python が t_import_file と stg_sales_line を入れた後に実行する。
-- =====================================================================
DELETE FROM t_sales_line;
DELETE FROM m_customer;
DELETE FROM m_product;

-- 名称はコードごとに最も新しい売上日の明細のもの（同じ日なら後に読んだもの）
INSERT INTO m_customer (customer_code, customer_name)
SELECT customer_code, customer_name
FROM (
    SELECT customer_code, customer_name,
           ROW_NUMBER() OVER (PARTITION BY customer_code ORDER BY sales_date DESC, load_seq DESC) AS rn
    FROM stg_sales_line
)
WHERE rn = 1;

INSERT INTO m_product (product_code, product_name)
SELECT product_code, product_name
FROM (
    SELECT product_code, product_name,
           ROW_NUMBER() OVER (PARTITION BY product_code ORDER BY sales_date DESC, load_seq DESC) AS rn
    FROM stg_sales_line
)
WHERE rn = 1;

INSERT INTO t_sales_line (
    slip_no, line_no, sales_date, ym, ym_idx, customer_code, region, staff, product_code, category,
    quantity, unit_price, unit_cost, sales_amount, cost_amount, gross_profit, file_id, source_row)
SELECT
    slip_no, line_no, sales_date,
    substr(sales_date, 1, 7),
    CAST(substr(sales_date, 1, 4) AS INTEGER) * 12 + CAST(substr(sales_date, 6, 2) AS INTEGER) - 1,
    customer_code, region, staff, product_code, category,
    quantity, unit_price, unit_cost,
    quantity * unit_price,
    quantity * unit_cost,
    quantity * unit_price - quantity * unit_cost,
    file_id, source_row
FROM stg_sales_line
ORDER BY load_seq;

DELETE FROM stg_sales_line;
