from __future__ import annotations

import multiprocessing
import socket
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import BrowserContext, expect, sync_playwright

from prompt_mutator.web import create_app


def _serve(port: int, runs_root: str) -> None:
    uvicorn.run(
        create_app(runs_root=Path(runs_root)),
        host="127.0.0.1",
        port=port,
        log_level="error",
    )


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def web_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    runs_root = tmp_path_factory.mktemp("browser-runs")
    process = multiprocessing.get_context("spawn").Process(
        target=_serve,
        args=(port, str(runs_root)),
        daemon=True,
    )
    process.start()
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{base_url}/api/health", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("web test server did not start")
        yield base_url
    finally:
        process.terminate()
        process.join(timeout=5)


@pytest.fixture(scope="module")
def browser_context(web_server: str):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin=web_server,
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()


def test_help_theme_and_responsive_modal(
    browser_context: BrowserContext,
    web_server: str,
) -> None:
    page = browser_context.new_page()
    page.goto(web_server)

    page.locator("#help-toggle").click()
    expect(page.locator("#help-modal")).to_be_visible()
    expect(page.locator("#help-modal")).to_contain_text("HTML Entity")
    expect(page.locator("#help-modal")).to_contain_text("URL")
    page.locator("#close-help").click()

    original_theme = page.locator("html").get_attribute("data-theme")
    page.locator("#theme-toggle").click()
    changed_theme = page.locator("html").get_attribute("data-theme")
    assert changed_theme != original_theme
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", changed_theme)

    page.set_viewport_size({"width": 390, "height": 760})
    page.locator("#help-toggle").click()
    box = page.locator("#help-modal").bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["y"] >= 0
    assert box["width"] <= 390 and box["height"] <= 760
    page.close()


def test_generation_inspection_sorting_and_exact_clipboard_values(
    browser_context: BrowserContext,
    web_server: str,
) -> None:
    page = browser_context.new_page()
    page.goto(web_server)
    page.locator("#prompt-input").fill("Review this café text")
    page.locator("#generate-button").click()

    rows = page.locator("#case-rows tr")
    expect(rows).to_have_count(25, timeout=15_000)
    expect(page.locator('[data-sort="technique_label"]')).to_contain_text("↑")
    page.locator('[data-sort="escaped"]').click()
    expect(page.locator('[data-sort="escaped"]')).to_contain_text("↑")

    first_row = rows.first
    first_row.click()
    expect(page.locator("#inspection-modal")).to_be_visible()
    raw_value = page.locator("#rendered-value").text_content()
    encoded_value = page.locator("#encoded-value").text_content()
    assert raw_value
    assert encoded_value and encoded_value.startswith("\\u")
    assert encoded_value != raw_value
    page.locator("#close-inspection").click()

    first_row.locator(".row-copy-button").nth(0).click()
    copied_raw = page.evaluate("navigator.clipboard.readText()")
    assert copied_raw == raw_value
    expect(page.locator("#inspection-modal")).not_to_be_visible()

    first_row.locator(".row-copy-button").nth(1).click()
    copied_encoded = page.evaluate("navigator.clipboard.readText()")
    assert copied_encoded == encoded_value

    page.keyboard.press("Control+M")
    expect(page.locator("body")).to_have_class("results-focus")
    page.keyboard.press("Control+M")
    expect(page.locator("body")).not_to_have_class("results-focus")
    page.close()
