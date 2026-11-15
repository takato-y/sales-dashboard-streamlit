"""テスト用の小さな明細を作る補助関数。"""

from __future__ import annotations

import io

import pandas as pd

from sales_dashboard import schema as s

HEADER = s.REQUIRED_COLUMNS


def row(slip="S1", line=1, day="2025-01-06", cust="C001", cname="得意先A", region="関東",
        staff="佐藤", prod="P1", pname="商品A", cat="食品", qty=1, price=100, cost=70) -> list:
    return [slip, line, day, cust, cname, region, staff, prod, pname, cat, qty, price, cost]


def to_csv_bytes(rows: list[list], encoding="utf-8", header=HEADER) -> bytes:
    return pd.DataFrame(rows, columns=header).to_csv(index=False).encode(encoding)


def to_xlsx_bytes(rows: list[list], header=HEADER) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=header).to_excel(buf, index=False)
    return buf.getvalue()
