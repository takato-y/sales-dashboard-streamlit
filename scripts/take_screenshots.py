"""起動中の画面を Playwright（ヘッドレスの Chromium）で撮影し、docs/images/ に保存する。

事前に別の端末で画面を起動しておく:
  streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8599
撮影:
  python scripts/take_screenshots.py [--url http://127.0.0.1:8599]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
VIEW_HEIGHT = 1900  # Streamlit は内側の領域がスクロールするため、全体が入る高さで撮る
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def wait_idle(page: Page, extra_ms: int = 1500) -> None:
    """Streamlit の再描画が終わるまで待つ。"""
    page.wait_for_timeout(500)
    page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=60_000)
    page.wait_for_timeout(extra_ms)
    if page.locator('[data-testid="stException"]').count():
        raise SystemExit("画面に例外が表示されています。撮影を中止します。")


def open_tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    wait_idle(page)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8599")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": VIEW_HEIGHT}, locale="ja-JP")
        page.goto(a.url)
        page.wait_for_selector('[data-testid="stMetric"]', timeout=90_000)
        wait_idle(page, 2500)
        page.screenshot(path=OUT / "01_概要.png")

        open_tab(page, "ABC分析")
        page.screenshot(path=OUT / "02_ABC分析.png")

        open_tab(page, "地域・担当別")
        page.screenshot(path=OUT / "03_地域・担当別.png")

        # 誤りを含むサンプルを読み込んだ状態の取込結果
        page.get_by_text("ファイルを読み込む").click()
        wait_idle(page)
        page.locator('input[type="file"]').set_input_files(
            [str(SAMPLES / "sales_sample_2025-01.csv"), str(SAMPLES / "sales_errors_sample.csv")])
        wait_idle(page, 2500)
        open_tab(page, "取込結果")
        page.screenshot(path=OUT / "04_取込結果.png")
        browser.close()
    print("saved:", ", ".join(sorted(x.name for x in OUT.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
