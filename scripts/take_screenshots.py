"""起動中の画面を Playwright（ヘッドレスの Chromium）で撮影し、docs/images/ に保存する。

事前に別の端末で画面を起動しておく:
  streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8599
撮影:
  python scripts/take_screenshots.py [--url http://127.0.0.1:8599] [--work 作業用フォルダ]

画面に例外が表示されたら撮影を中止する。印刷用ページは画面からダウンロードしたファイルを
そのまま開いて撮影し、同じページを Chromium の印刷機能で PDF にして作業用フォルダに保存する。
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
SAMPLES = ROOT / "samples"
VIEW_WIDTH = 1440
VIEW_HEIGHT = 2200  # Streamlit は内側の領域がスクロールするため、全体が入る高さで描画してから切り抜く


def wait_idle(page: Page, extra_ms: int = 1500) -> None:
    """Streamlit の再描画が終わるまで待ち、例外の表示がないことを確かめる。"""
    page.wait_for_timeout(500)
    page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=60_000)
    page.wait_for_timeout(extra_ms)
    if page.locator('[data-testid="stException"]').count():
        raise SystemExit("画面に例外が表示されています。撮影を中止します。")


def shot(page: Page, name: str) -> None:
    """本文とサイドバーの中身が収まる高さで切り抜いて保存する。"""
    bottom = page.evaluate("""() => {
        const els = ['[data-testid="stMainBlockContainer"]', '[data-testid="stSidebarUserContent"]']
            .map(s => document.querySelector(s)).filter(Boolean);
        return Math.max(...els.map(e => e.getBoundingClientRect().bottom));
    }""")
    height = min(VIEW_HEIGHT, int(bottom) + 40)
    page.screenshot(path=OUT / name, clip={"x": 0, "y": 0, "width": VIEW_WIDTH, "height": height})


def open_tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    wait_idle(page)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8599")
    ap.add_argument("--work", default=None, help="ダウンロードした印刷用ページと PDF の保存先（省略時は一時フォルダ）")
    a = ap.parse_args()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="sales_dashboard_"))
    work.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": VIEW_WIDTH, "height": VIEW_HEIGHT}, locale="ja-JP",
                                accept_downloads=True)
        page.goto(a.url)
        page.wait_for_selector('[data-testid="stMetric"]', timeout=90_000)
        wait_idle(page, 2500)
        shot(page, "01_概要.png")

        open_tab(page, "ABC分析")
        shot(page, "02_ABC分析.png")

        open_tab(page, "地域・担当別")
        shot(page, "03_地域・担当別.png")

        open_tab(page, "出力")
        shot(page, "04_出力.png")
        with page.expect_download() as dl:
            page.get_by_role("button", name="印刷用ページを保存").click()
        html_path = work / "print_view.html"
        dl.value.save_as(html_path)
        with page.expect_download() as dl:
            page.get_by_role("button", name="Excel で保存").click()
        dl.value.save_as(work / "export.xlsx")

        # 印刷用ページ：画面幅（A4 相当）での表示と、印刷（PDF）の結果
        view = browser.new_page(viewport={"width": 900, "height": 1200}, locale="ja-JP")
        view.goto(html_path.as_uri())
        view.wait_for_timeout(800)
        view.screenshot(path=OUT / "05_印刷用ページ.png", clip={"x": 0, "y": 0, "width": 900, "height": 1200})
        view.pdf(path=str(work / "print_view.pdf"), prefer_css_page_size=True, print_background=True)
        view.close()

        # 誤りを含むサンプルを読み込んだ状態の取込結果
        page.get_by_text("ファイルを読み込む").click()
        wait_idle(page)
        page.locator('input[type="file"]').set_input_files(
            [str(SAMPLES / "sales_sample_2025-01.csv"), str(SAMPLES / "sales_errors_sample.csv")])
        wait_idle(page, 2500)
        open_tab(page, "取込結果")
        shot(page, "06_取込結果.png")
        browser.close()
    print("saved:", ", ".join(sorted(x.name for x in OUT.glob("*.png"))))
    print("work:", ", ".join(sorted(x.name for x in work.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
