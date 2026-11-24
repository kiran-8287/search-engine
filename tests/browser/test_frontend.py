"""Browser checks use an isolated fixture release and an ephemeral loopback socket."""
from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from playwright.sync_api import expect

from techsearch.api import create_app
from techsearch.experiments import save_report

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


def search(page, value):
    field = page.get_by_label("Search the corpus", exact=True)
    field.fill(value)
    field.press("Enter")


def no_page_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_home_keyboard_and_snapshot_navigation(page, base):
    page.goto(base)
    expect(page.get_by_role("heading", name="TechSearch", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="CSS grid", exact=True)).to_be_visible()
    field = page.get_by_label("Search the corpus", exact=True)
    page.keyboard.press("/")
    expect(field).to_be_focused()
    search(page, "fixturefolio")
    expect(page.locator(".masthead #query")).to_be_visible()
    expect(page.get_by_role("heading", name="TechSearch", exact=True)).not_to_be_visible()
    expect(page.locator("#status")).to_contain_text("Page 1 of 2")
    first = page.locator("#results .result-title").first.inner_text()
    with page.expect_request(lambda request: "/api/v1/search/" in request.url and "page=2" in request.url):
        page.get_by_role("button", name="Next").click()
    expect(page.locator("#status")).to_contain_text("Page 2 of 2")
    expect(page.locator("#results > li")).to_have_count(2)
    assert parse_qs(urlsplit(page.url).query) == {"q": ["fixturefolio"], "page": ["2"]}

    page.reload()
    expect(page.locator("#status")).to_contain_text("Page 2 of 2")
    page.go_back()
    expect(page.locator("#status")).to_contain_text("Page 1 of 2")
    expect(page.locator("#results .result-title").first).to_have_text(first)
    page.go_forward()
    expect(page.locator("#status")).to_contain_text("Page 2 of 2")
    page.keyboard.press("Control+k")
    expect(field).to_be_focused()
    expect(field).to_have_value("fixturefolio")
    no_page_overflow(page)


def test_filters_attribution_feedback_and_search_lab_navigation(page, base):
    page.goto(base)
    search(page, "query selector")
    expect(page.locator("#warnings")).to_contain_text("Dense search is unavailable")
    stack = page.get_by_role("tab", name="Stack Overflow")
    stack.click()
    expect(stack).to_have_attribute("aria-selected", "true")
    expect(page.locator("#results > li")).to_have_count(1)
    expect(page.locator("#results .accepted")).to_be_visible()
    topic = page.get_by_label("Topic", exact=True)
    expect(topic.locator('option[value="dom"]')).to_have_count(1)
    topic.select_option("dom")
    expect(page.locator("#status")).to_have_text("1 result")
    params = {"q": ["query selector"], "source": ["stackoverflow"], "topic": ["dom"]}
    assert parse_qs(urlsplit(page.url).query) == params

    row = page.locator("#results > li").first
    row.get_by_text("Attribution", exact=True).click()
    expect(row.get_by_role("link", name="Fixture author")).to_be_visible()
    expect(row.get_by_text("CC BY-SA 4.0", exact=True)).to_be_visible()
    row.locator("summary[aria-label^='Feedback for']").click()
    vote = row.get_by_role("button", name="Not relevant", exact=True)
    vote.click()
    expect(vote).to_have_attribute("aria-pressed", "true")
    row.get_by_role("button", name="Relevant", exact=True).click()
    expect(row.get_by_role("button", name="Relevant", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#status")).to_contain_text("Feedback saved")
    with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/v1/search")) as submission:
        page.get_by_role("button", name="Refine with feedback").click()
    assert submission.value.post_data_json["apply_feedback"] is True
    expect(page.locator("#results > li")).to_have_count(1)

    page.get_by_role("link", name="IR Lab").click()
    expect(page.get_by_role("heading", name="Information retrieval lab", exact=True)).to_be_visible()
    page.get_by_role("link", name="Search", exact=True).click()
    expect(page.get_by_label("Search the corpus", exact=True)).to_have_value("query selector")
    expect(stack).to_have_attribute("aria-selected", "true")
    expect(topic).to_have_value("dom")
    assert parse_qs(urlsplit(page.url).query) == params

    mdn = page.get_by_role("tab", name="MDN Docs")
    mdn.click()
    expect(page.locator("#results .source-label").first).to_contain_text("MDN Web Docs")
    mdn.press("Home")
    expect(page.get_by_role("tab", name="All results")).to_have_attribute("aria-selected", "true")
    assert "source" not in parse_qs(urlsplit(page.url).query)


def test_lab_search_link_restores_filters_before_lab_script_loads(page, base):
    page.goto(base)
    search(page, "query selector")
    page.get_by_role("tab", name="Stack Overflow").click()
    expect(page.locator("#results > li")).to_have_count(1)
    topic = page.get_by_label("Topic", exact=True)
    expect(topic.locator('option[value="dom"]')).to_have_count(1)
    topic.select_option("dom")
    expect(page.locator("#status")).to_have_text("1 result")
    original_url = page.url

    page.route("**/assets/js/lab.js", lambda route: route.abort())
    page.get_by_role("link", name="IR Lab").click()
    expect(page.get_by_role("heading", name="Information retrieval lab", exact=True)).to_be_visible()
    page.get_by_role("link", name="Search", exact=True).click()

    expect(page).to_have_url(original_url)
    expect(page.get_by_label("Search the corpus", exact=True)).to_have_value("query selector")
    expect(page.get_by_role("tab", name="Stack Overflow")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_label("Topic", exact=True)).to_have_value("dom")


def test_desktop_preview_scroll_sections_and_safe_code(page, base):
    page.set_viewport_size({"width": 1400, "height": 720})
    page.goto(base)
    preview = page.get_by_role("dialog")
    expect(preview).not_to_be_visible()
    search(page, "fixturefolio")
    expect(page.locator("#results > li")).to_have_count(10)
    trigger = page.get_by_role("button", name="Preview", exact=True).nth(8)
    trigger.scroll_into_view_if_needed()
    before = page.evaluate("window.scrollY")
    assert before > 0
    trigger.click()
    expect(preview.get_by_role("button", name="Close preview")).to_be_focused()
    assert not page.locator("#preview").evaluate("(node) => node.matches(':modal')")
    assert page.evaluate("window.scrollY") == before
    expect(page.locator("#results > li")).to_have_count(10)
    page.keyboard.press("Escape")
    expect(preview).not_to_be_visible()
    expect(trigger).to_be_focused()
    assert page.evaluate("window.scrollY") == before

    search(page, "code:===")
    expect(page.locator("#results > li")).to_have_count(1)
    page.get_by_role("button", name="Preview", exact=True).click()
    expect(preview.locator("pre")).to_contain_text("<img src=x onerror")
    assert preview.locator("pre code").text_content().startswith("  const result")
    expect(preview.locator("img")).to_have_count(0)
    expect(preview.get_by_text("MDN contributors", exact=True)).to_be_visible()
    preview.get_by_role("button", name="Syntax").click()
    expect(preview.locator(".preview-excerpt")).to_contain_text("Use Promise.all for concurrent tasks")
    expect(preview.get_by_role("link", name="Open original source")).to_have_attribute(
        "href", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/FixturePromise#syntax"
    )
    preview.get_by_role("button", name="Close preview").click()
    expect(preview).not_to_be_visible()
    no_page_overflow(page)


def test_mobile_preview_modal_focus_and_error(page, base):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base)
    search(page, "code:===")
    trigger = page.get_by_role("button", name="Preview", exact=True)
    expect(trigger).to_be_visible()
    assert page.locator(".result-origin").evaluate("""(node) => {
        const source = node.querySelector('.source-label').getBoundingClientRect();
        const path = node.querySelector('.breadcrumb').getBoundingClientRect();
        return source.right <= path.left;
    }""")
    preview = page.get_by_role("dialog")
    before = page.url
    page.route("**/api/v1/documents/**", lambda route: route.fulfill(status=503, json={"detail": "Evidence unavailable"}))
    trigger.click()
    expect(preview).to_contain_text("Could not load the source excerpt. Evidence unavailable")
    expect(preview.get_by_role("link", name="Open original source")).to_be_visible()
    assert page.locator("#preview").evaluate("(node) => node.matches(':modal')")
    expect(preview.get_by_role("button", name="Close preview")).to_be_focused()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('#preview') !== null")
    page.keyboard.press("Escape")
    expect(preview).not_to_be_visible()
    expect(trigger).to_be_focused()
    assert page.url == before
    page.unroute("**/api/v1/documents/**")
    trigger.click()
    expect(preview.locator("pre")).to_contain_text("const result")
    no_page_overflow(page)
    preview.get_by_role("button", name="Close preview").click()
    no_page_overflow(page)


def test_search_loading_empty_and_error_states(page, base):
    page.add_init_script("""
        const original = window.fetch.bind(window);
        window.pauseSearch = true;
        window.fetch = (url, opts) => {
          if (window.pauseSearch && url === '/api/v1/search') {
            return new Promise((resolve, reject) => {
              window.resumeSearch = () => original(url, opts).then(resolve, reject);
            });
          }
          return original(url, opts);
        };
    """)
    page.goto(base)
    search(page, 'title:"unterminated')
    status = page.locator("#status")
    expect(status).to_have_text("Searching…")
    page.evaluate("window.pauseSearch = false; window.resumeSearch()")
    expect(status).to_contain_text("Close the quoted text")
    search(page, "zppxyzqq")
    expect(status).to_contain_text("No matches")
    expect(page.locator("#results > li")).to_have_count(0)


def test_lab_controls_comparison_and_reports(page, base):
    page.goto(base + "/lab")
    expect(page.get_by_role("heading", name="Information retrieval lab")).to_be_visible()
    expect(page.get_by_role("table", name="Index summary")).to_be_visible()
    navigation = page.get_by_role("navigation", name="Lab sections")
    navigation.get_by_role("link", name="Compare searches").click()
    expect(page.get_by_label("Mode", exact=True).first.locator("option")).to_have_count(8)
    page.get_by_label("Comparison query").fill("Promise.all")
    page.get_by_role("button", name="Compare", exact=True).click()
    expect(page.locator("#status")).to_have_text("Comparison ready.")
    expect(page.get_by_text("This release has no dense passages", exact=False)).to_be_visible()
    expect(page.get_by_text("Execution trace", exact=True)).to_be_visible()
    assert page.request.get(base + page.get_by_role("link", name="Export ranking").get_attribute("href")).ok
    navigation.get_by_role("link", name="Compression", exact=True).click()
    expect(page.get_by_role("table", name="Compression sizes")).to_be_visible()
    expect(page.locator("#report progress")).to_have_count(3)
    expect(page.get_by_role("link", name="Export JSON", exact=True)).to_be_visible()
    navigation.get_by_role("link", name="Speed & execution").click()
    expect(page.get_by_text("The TAAT/DAAT timing and equivalence check has not been generated", exact=False)).to_be_visible()
    page.set_viewport_size({"width": 320, "height": 740})
    no_page_overflow(page)


def test_lab_sections_history_and_release_attribution(page, base, settings, release):
    archived = SimpleNamespace(id="a" * 24)
    for split, repeats in (("dev", 3), ("test", 8)):
        save_report(settings, archived, "benchmark-" + split, {
            "split": split, "repeats": repeats, "release_id": archived.id,
            "outcomes": {"bm25": {"ok": 2}}, "latency_note": "Fixture reader conditions",
        })
    save_report(settings, archived, "evaluation-ablations-dev", {
        "split": "dev", "status": "blocked", "reason": "Missing annotation configuration", "pending": 5,
    })
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/lab")
    nav = page.get_by_role("navigation", name="Lab sections")
    expect(nav.get_by_role("link")).to_have_count(7)
    expect(page.get_by_label("Lab section", exact=True)).not_to_be_visible()
    expect(page.get_by_role("table", name="Index summary")).to_contain_text(release.id)

    compare = nav.get_by_role("link", name="Compare searches")
    compare.focus()
    compare.press("Enter")
    expect(page.locator("#section-title")).to_be_focused()
    page.get_by_label("Comparison query").fill("Promise.all")
    page.locator("#method-a-ranker").select_option("tfidf")
    page.locator("#method-a-source").select_option("mdn")
    topic = page.locator("#method-a-topic")
    expect(topic.locator('option[value="javascript"]')).to_have_count(1)
    topic.select_option("javascript")
    page.get_by_text("Authority & diversification", exact=True).first.click()
    page.get_by_label("MDN authority").first.check()
    links = nav.get_by_role("link", name="Link analysis")
    links.click()
    expect(page.get_by_role("table", name="Graph summary")).to_be_visible()
    nav.get_by_role("link", name="Topics & clusters").click()
    expect(page.get_by_text("sampled LSI and K-means report has not been generated", exact=False)).to_be_visible()
    nav.get_by_role("link", name="Speed & execution").click()
    expect(page.locator("#report")).to_contain_text("Active release " + release.id)
    expect(page.locator("#report")).to_contain_text("has not been generated for the active release")
    expect(page.get_by_role("table", name="Benchmark settings")).to_have_count(0)

    page.get_by_label("Saved report release").select_option(archived.id)
    expect(page.locator(".report-release.historical")).to_have_text("Historical release " + archived.id)
    settings_table = page.get_by_role("table", name="Benchmark settings")
    expect(settings_table.get_by_role("row", name="Repeats 3")).to_be_visible()
    page.get_by_label("Query split").select_option("test")
    expect(settings_table.get_by_role("row", name="Repeats 8")).to_be_visible()
    expect(page.get_by_role("link", name="Export JSON")).to_have_attribute(
        "href", "/api/v1/exports/reports/benchmark-test?release=" + archived.id,
    )
    page.go_back()
    expect(page.get_by_label("Query split")).to_have_value("dev")
    expect(settings_table.get_by_role("row", name="Repeats 3")).to_be_visible()
    page.go_forward()
    expect(page.get_by_label("Query split")).to_have_value("test")
    expect(settings_table.get_by_role("row", name="Repeats 8")).to_be_visible()

    nav.get_by_role("link", name="Evaluation").click()
    expect(page.get_by_label("Query split")).to_have_value("test")
    expect(page.locator("#report")).to_contain_text("The judged relevance report has not been generated")
    page.get_by_label("Query split").select_option("dev")
    page.get_by_label("Evaluation view").select_option("features")
    expect(page.locator("#report")).to_contain_text("Missing annotation configuration")
    expect(page.locator("#report")).to_contain_text("5 pending judgments")
    expect(page.get_by_role("table", name="Relevance metrics")).to_have_count(0)
    page.get_by_label("Evaluation view").select_option("protocol")
    expect(page.get_by_role("table", name="Evaluation report status")).to_contain_text("Blocked")
    expect(page.locator("#report")).to_contain_text("Keep Test held out until settings are final.")

    nav.get_by_role("link", name="Overview").click()
    expect(page.get_by_role("table", name="Index summary")).to_contain_text(release.id)
    compare.click()
    expect(page.get_by_label("Comparison query")).to_have_value("Promise.all")
    page.get_by_role("link", name="Search", exact=True).click()
    page.get_by_role("link", name="IR Lab").click()
    expect(page.locator("#section-title")).to_have_text("Compare searches")
    expect(page.get_by_label("Comparison query")).to_have_value("Promise.all")
    expect(page.locator("#method-a-ranker")).to_have_value("tfidf")
    expect(page.locator("#method-a-source")).to_have_value("mdn")
    expect(page.locator("#method-a-topic")).to_have_value("javascript")
    expect(page.get_by_label("MDN authority").first).to_be_checked()
    page.set_viewport_size({"width": 320, "height": 740})
    expect(nav).not_to_be_visible()
    page.get_by_role("combobox", name="Lab section", exact=True).select_option("compression")
    expect(page.locator("#section-title")).to_have_text("Compression")
    no_page_overflow(page)
    assert not errors
