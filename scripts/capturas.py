"""Saca capturas del widget funcionando en los sitios de ejemplo (requiere run_demo.py corriendo)."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "capturas"

CASES = [
    ("tienda_stock", "http://localhost:8101/", ["Hola", "¿tenés stock de los auriculares Sonix?", "y el parlante portátil?"]),
    ("tienda_chocotorta", "http://localhost:8101/", ["me das la receta de la chocotorta?"]),
    ("pasteleria_chocotorta", "http://localhost:8102/", ["me das la receta de la chocotorta?"]),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, url, qs in CASES:
            page = await b.new_page(viewport={"width": 1100, "height": 760})
            await page.goto(url)
            await page.wait_for_selector("#sabio-widget", state="attached")
            await page.locator("#sabio-widget .btn").click()
            for q in qs:
                await page.locator("#sabio-widget input").fill(q)
                await page.locator("#sabio-widget input").press("Enter")
                await page.wait_for_function(
                    "() => !document.querySelector('#sabio-widget').shadowRoot.querySelector('.typing')")
                await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT / f"{name}.png"))
            await page.close()
        page = await b.new_page(viewport={"width": 1200, "height": 900})
        await page.goto("http://localhost:8000/admin")
        await page.wait_for_selector("#list tr")
        await page.locator("#list tr").last.click()
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "panel.png"), full_page=True)
        await b.close()


asyncio.run(main())
