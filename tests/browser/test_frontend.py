"""Browser checks use an isolated fixture release and an ephemeral loopback socket."""
from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import expect

from techsearch.api import create_app

pytestmark = pytest.mark.browser


@pytest.fixture
def base(settings, release):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            until = time.monotonic() + 10
            while not server.started and worker.is_alive() and time.monotonic() < until:
                time.sleep(.025)
            if not server.started:
                pytest.fail("Local browser fixture did not start.")
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            worker.join(timeout=10)


def test_search_keyboard_pagination_evidence_and_safe_html(page, base):
    page.goto(base)
    page.keyboard.press("/")
    field = page.get_by_label("Search the corpus", exact=True)
    expect(field).to_be_focused()
    field.fill("fixturefolio")
    field.press("Enter")
    expect(page.get_by_text("Page 1 of 2")).to_be_visible()
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_text("Page 2 of 2")).to_be_visible()
    expect(page.locator("#results > li")).to_have_count(2)
    field.fill("code:===")
    field.press("Enter")
    expect(page.locator("#results > li")).to_have_count(1)
    page.get_by_role("button", name="View evidence").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("pre")).to_contain_text("<img src=x onerror")
    expect(dialog.locator("img")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    field.fill("zppxyzqq")
    field.press("Enter")
    expect(page.get_by_role("status")).to_contain_text("No matches")


def test_search_loading_and_error(page, base):
    page.add_init_script("""
        const original = window.fetch.bind(window);
        window.fetch = (url, opts) => {
          if (url === '/api/v1/search') {
            return new Promise((resolve, reject) => {
              window.resumeSearch = () => original(url, opts).then(resolve, reject);
            });
          }
          return original(url, opts);
        };
    """)
    page.goto(base)
    page.locator("#query").fill('title:"unterminated')
    page.get_by_role("button", name="Search", exact=True).click()
    expect(page.get_by_role("status")).to_have_text("Searching…")
    page.evaluate("window.resumeSearch()")
    expect(page.get_by_role("status")).to_contain_text("Close the quoted text")


def test_lab_comparison_and_missing_experiment(page, base):
    page.goto(base + "/lab")
    expect(page.get_by_role("heading", name="Information retrieval lab.")).to_be_visible()
    page.locator("#query").fill("Promise.all")
    page.get_by_role("button", name="Compare", exact=True).click()
    expect(page.get_by_role("status")).to_have_text("Comparison ready.")
    expect(page.get_by_text("This release has no dense passages", exact=False)).to_be_visible()
    page.get_by_role("button", name="TAAT / DAAT").click()
    expect(page.get_by_text("This experiment has not been run", exact=False)).to_be_visible()
