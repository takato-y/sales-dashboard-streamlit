"""架空の売上明細をファイルに出力する（REQ-010）。

使い方:
  python scripts/generate_data.py                       # data/generated/ に月別 CSV を 24 本
  python scripts/generate_data.py --format xlsx         # 月別 Excel
  python scripts/generate_data.py --single --rows-per-month 4200   # 1 本にまとめる（性能確認用）
  python scripts/generate_data.py --samples             # samples/ のサンプルを作り直す
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sales_dashboard import generator  # noqa: E402
from sales_dashboard import schema as s  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="架空の売上明細を生成する")
    ap.add_argument("--out", default=str(ROOT / "data" / "generated"), help="出力先フォルダ")
    ap.add_argument("--start", default="2024-01", help="開始年月（YYYY-MM）")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--rows-per-month", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--format", choices=["csv", "xlsx"], default="csv")
    ap.add_argument("--single", action="store_true", help="月別に分けず 1 ファイルにする")
    ap.add_argument("--samples", action="store_true", help="samples/ のサンプルファイルを作り直す")
    a = ap.parse_args()

    if a.samples:
        out = ROOT / "samples"
        out.mkdir(exist_ok=True)
        df = generator.generate_sales(seed=42, start="2025-01", months=1, lines_per_month=300)
        df.to_csv(out / "sales_sample_2025-01.csv", index=False, encoding="utf-8")
        generator.make_error_sample().to_csv(out / "sales_errors_sample.csv", index=False, encoding="utf-8")
        print(f"samples: {len(df)} 行 + エラー例")
        return 0

    df = generator.generate_sales(seed=a.seed, start=a.start, months=a.months,
                                  lines_per_month=a.rows_per_month)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.single:
        groups = [(f"sales_{a.start}_{a.months}m", df)]
    else:
        month = df[s.COL_DATE].str.slice(0, 7)
        groups = [(f"sales_{m}", g) for m, g in df.groupby(month)]
    for name, g in groups:
        path = out / f"{name}.{a.format}"
        if a.format == "csv":
            g.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            g.to_excel(path, index=False)
    print(f"{len(df)} 行を {len(groups)} ファイルに出力しました（{out.name}/）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
