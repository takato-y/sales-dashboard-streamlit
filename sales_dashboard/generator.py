"""デモ・性能測定用の架空の売上明細を生成する（REQ-010 / FN-010）。

出力する値はすべて架空。得意先名は架空の地名風の語と業態の組み合わせで作る。
乱数の種（seed）が同じなら、同じ明細が得られる。
"""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date

import pandas as pd

from . import schema as s

# 月ごとの季節係数（卸売の一般的な傾向：3 月の年度末・7 月の中元・12 月の歳末が多く、2 月・8 月が少ない）
SEASONALITY = {1: 0.88, 2: 0.82, 3: 1.12, 4: 0.97, 5: 0.95, 6: 1.00,
               7: 1.15, 8: 0.86, 9: 0.96, 10: 1.00, 11: 1.04, 12: 1.30}
# カテゴリ固有の季節係数（飲料は夏に、包装資材は年末に増える）
CATEGORY_SEASONALITY = {
    "飲料": {6: 1.25, 7: 1.45, 8: 1.50, 9: 1.15, 12: 0.85, 1: 0.80, 2: 0.80},
    "包装資材": {11: 1.20, 12: 1.35},
}
ANNUAL_GROWTH = 0.06  # 年 6% の伸び

REGIONS = ["北海道・東北", "関東", "中部", "近畿", "中国・四国", "九州"]
STAFF = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "中村", "小林"]
_NAME_HEADS = ["みなと台", "あさひ野", "しらかば", "つばめ", "こはる", "やまびこ", "かもめ", "ひばり丘",
               "わかば", "みずほ台", "さくら坂", "ゆうなぎ", "もみじ谷", "あおい", "なぎさ", "いろは",
               "ことぶき", "はやて", "すずらん", "ほたる川"]
_NAME_TAILS = ["食品", "商店", "ストア", "マート", "物産", "フーズ", "商事", "スーパー"]

# カテゴリ → (商品名の候補, 単価の範囲, 原価率の範囲)
_CATEGORIES = {
    "食品": (["業務用だし 1kg", "乾燥わかめ 500g", "冷凍うどん 5食", "レトルトカレー 10袋", "精米 5kg",
             "缶詰 ツナ 12缶", "パスタ 3kg", "小麦粉 10kg", "醤油 1.8L", "味噌 2kg", "冷凍餃子 50個",
             "食用油 16.5kg"], (380, 6800), (0.70, 0.80)),
    "飲料": (["緑茶 500ml 24本", "ミネラルウォーター 2L 6本", "炭酸水 500ml 24本", "缶コーヒー 30本",
             "麦茶パック 52袋", "野菜ジュース 24本", "スポーツドリンク 24本", "紅茶 1.5L 8本",
             "乳酸菌飲料 30本", "豆乳 1L 6本"], (900, 4200), (0.68, 0.78)),
    "日用品": (["食器用洗剤 4L", "ハンドソープ 詰替 2L", "ゴミ袋 45L 100枚", "トイレットペーパー 48R",
              "キッチンペーパー 24R", "ゴム手袋 100枚", "除菌シート 10個", "スポンジ 30個",
              "洗濯洗剤 4kg", "紙おしぼり 1000枚"], (450, 5200), (0.62, 0.74)),
    "文具": (["コピー用紙 A4 2500枚", "ボールペン 50本", "クリアファイル 100枚", "付箋 20冊",
             "ガムテープ 30巻", "ホッチキス針 20箱", "油性マーカー 10本", "伝票 複写 10冊"],
            (300, 3800), (0.55, 0.70)),
    "包装資材": (["ダンボール 60サイズ 50枚", "OPP袋 1000枚", "緩衝材 ロール", "ストレッチフィルム 6巻",
               "クラフト紙袋 200枚", "PPバンド 2巻", "食品トレー 500枚", "ラップ 業務用 6本"],
              (800, 9800), (0.66, 0.78)),
}


@dataclass(frozen=True)
class Customer:
    code: str
    name: str
    region: str
    staff: str
    weight: float  # 取引規模（大きいほど明細が多い）


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    category: str
    price: int
    cost: int


def make_masters(seed: int = 42, n_customers: int = 40) -> tuple[list[Customer], list[Product]]:
    """得意先・商品の架空マスタを作る。取引規模は偏り（パレート型）をもたせる。"""
    rng = random.Random(seed)
    names = [h + t for h in _NAME_HEADS for t in _NAME_TAILS]
    rng.shuffle(names)
    customers = []
    for i in range(n_customers):
        weight = rng.paretovariate(1.3)  # 少数の大口と多数の小口
        customers.append(Customer(
            code=f"C{i + 1:03d}", name=names[i], region=rng.choice(REGIONS),
            staff=STAFF[i % len(STAFF)], weight=weight,
        ))
    products = []
    pid = 1000
    for cat, (pnames, (lo, hi), (clo, chi)) in _CATEGORIES.items():
        for pname in pnames:
            pid += 1
            price = int(round(rng.uniform(lo, hi), -1))
            cost = int(round(price * rng.uniform(clo, chi)))
            products.append(Product(f"P{pid}", pname, cat, price, cost))
    return customers, products


def _business_days(year: int, month: int) -> list[date]:
    """土日と年末年始（12/29〜1/3）を除いた営業日。"""
    days = calendar.monthrange(year, month)[1]
    out = []
    for d in range(1, days + 1):
        day = date(year, month, d)
        if day.weekday() >= 5 or (month == 1 and d <= 3) or (month == 12 and d >= 29):
            continue
        out.append(day)
    return out


def generate_sales(seed: int = 42, start: str = "2024-01", months: int = 24,
                   lines_per_month: int = 1200, return_rate: float = 0.005) -> pd.DataFrame:
    """架空の売上明細を生成し、入力ファイルと同じ列の DataFrame で返す。

    lines_per_month は季節係数・伸び率をかける前の 1 か月あたりの明細数の目安。
    """
    rng = random.Random(seed)
    customers, products = make_masters(seed)
    cust_weights = [c.weight for c in customers]
    by_cat: dict[str, list[Product]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    categories = list(by_cat)

    first = pd.Period(start, freq="M")
    rows: list[list] = []
    for m in range(months):
        period = first + m
        factor = SEASONALITY[period.month] * (1 + ANNUAL_GROWTH) ** (m / 12)
        n_lines = int(lines_per_month * factor)
        days = _business_days(period.year, period.month)
        cat_weights = [CATEGORY_SEASONALITY.get(c, {}).get(period.month, 1.0) for c in categories]
        slip_no = 0
        made = 0
        while made < n_lines:
            slip_no += 1
            cust = rng.choices(customers, weights=cust_weights)[0]
            day = rng.choice(days)
            slip = f"S{period.year % 100:02d}{period.month:02d}-{slip_no:04d}"
            for line in range(1, rng.randint(1, 5) + 1):
                cat = rng.choices(categories, weights=cat_weights)[0]
                prod = rng.choice(by_cat[cat])
                qty = max(1, int(rng.lognormvariate(1.8, 0.7)))
                if rng.random() < return_rate:
                    qty = -max(1, qty // 3)  # 返品
                # 単価は得意先ごとの値引きを想定して ±3% 揺らす
                price = int(round(prod.price * rng.uniform(0.97, 1.03)))
                rows.append([slip, line, day.isoformat(), cust.code, cust.name, cust.region, cust.staff,
                             prod.code, prod.name, prod.category, qty, price, prod.cost])
                made += 1
    return pd.DataFrame(rows, columns=s.REQUIRED_COLUMNS)


def make_error_sample(seed: int = 7) -> pd.DataFrame:
    """検証で除外される行を含むサンプル（docs/04 の 4. サンプルファイル）を作る。

    正しい行の中に、日付の誤り・数量の空欄・単価の誤り・重複・必須項目の空欄・
    数式に見える得意先名（出力時の無害化の確認用）を混ぜる。
    """
    df = generate_sales(seed=seed, start="2025-02", months=1, lines_per_month=20).astype(object)
    df = df.head(20).reset_index(drop=True)
    df.loc[2, s.COL_DATE] = "2025-02-30"           # 存在しない日付
    df.loc[4, s.COL_QTY] = ""                       # 数量の空欄
    df.loc[6, s.COL_PRICE] = "千円"                 # 数値でない単価
    df.loc[8, s.COL_CUST_NAME] = ""                 # 必須項目の空欄
    df.loc[10, s.COL_QTY] = 0                       # 数量 0
    df.loc[12, s.COL_COST] = -100                   # 原価単価がマイナス
    df.loc[14, s.COL_CUST_NAME] = "=HYPERLINK(\"http://example.com\",\"確認\")"  # 数式に見える値（正しい行）
    df.loc[15, s.COL_PRICE] = "１，２８０円"        # 全角・カンマ・円（整形して受け付ける）
    dup = df.loc[[1]].copy()                        # 明細の重複
    df = pd.concat([df, dup], ignore_index=True)
    return df
