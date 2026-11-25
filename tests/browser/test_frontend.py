"""Browser checks use an isolated fixture release and an ephemeral loopback socket."""
from __future__ import annotations

import socket
import threading
import time
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


def test_lab_method_mapping_controls_preview_and_navigation(page, base):
    sent = []

    def record_comparison(route):
        sent.append(route.request.post_data_json)
        route.continue_()

    page.route("**/api/v1/compare", record_comparison)
    page.goto(base + "/lab")
    nav = page.get_by_role("navigation", name="IR Lab tabs")
    expect(nav.get_by_role("link")).to_have_count(3)
    expect(page.get_by_role("heading", name="Model comparison")).to_be_visible()
    nav.get_by_role("link", name="Try a query").click()
    query = page.get_by_label("Comparison query")
    query.fill("Promise.all")
    a, b = [page.get_by_role("group", name=f"Method {side}") for side in ("A", "B")]
    select_a = a.get_by_label("Retrieval method A")
    select_b = b.get_by_label("Retrieval method B")
    expect(select_a.locator("option")).to_have_text(["TF-IDF", "BM25", "Query likelihood", "Semantic", "Hybrid"])
    a.get_by_text("Advanced options", exact=True).click()
    a.get_by_label("Execution").select_option("daat")
    a.get_by_label("BM25 k₁").fill("1.4")
    select_b.select_option("bm25")
    for key, mode, ranker in (
        ("tfidf", "keyword", "tfidf"), ("bm25", "keyword", "bm25"), ("likelihood", "keyword", "likelihood"),
        ("dense", "semantic", None), ("hybrid", "hybrid", "bm25"),
    ):
        select_a.select_option(key)
        query.press("Enter")
        expect(page.locator("#status")).to_have_text("Comparison ready.")
        left = sent[-1]["left"]
        assert left["query"] == "Promise.all" and left["page_size"] == 5
        assert left["mode"] == mode and left.get("ranker") == ranker
        assert (left.get("strategy") == "daat") == (key in {"tfidf", "bm25", "hybrid"})
        assert ("k1" in left) == (key in {"bm25", "hybrid"})
    right = page.locator(".rank-panel").nth(1)
    assert 1 <= right.locator(".results > li").count() <= 5
    expect(right.get_by_text("Execution details")).to_be_visible()
    expect(right.locator("details.diagnostic[open]")).to_have_count(0)
    right.get_by_role("button", name="Preview", exact=True).first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    nav.get_by_role("link", name="Course experiments").click()
    expect(page.get_by_role("heading", name="Course experiments")).to_be_visible()
    page.go_back()
    expect(query).to_have_value("Promise.all")
    expect(select_a).to_have_value("hybrid")
    page.get_by_role("link", name="Search", exact=True).click()
    page.get_by_role("link", name="IR Lab").click()
    nav.get_by_role("link", name="Try a query").click()
    expect(query).to_have_value("Promise.all")
    expect(select_a).to_have_value("hybrid")


def test_lab_metric_formatting_and_stale_data_on_mobile(page, base, settings, release):
    from techsearch.evaluation import LAB_METHODS

    run = {"split": "dev", "run_id": "dev-fixture", "created_at": "2026-11-24T00:00:00Z",
           "query_count": 10, "paired_queries": 8, "repeats": 3, "candidate_depth": 150,
           "timing_ms": {key: {"warm": {"p50": index + 0.126, "p95": index + 2.126}}
                         for index, key in enumerate(LAB_METHODS)},
           "outcomes": {key: {"ok": 8, "unavailable": 2} for key in LAB_METHODS}}
    response = {"release_id": release.id, "configuration": settings.fingerprint,
                "documents": 10, "measurement": run, "quality": {"pending": 18}}
    page.route("**/api/v1/lab", lambda route: route.fulfill(json=response))
    save_report(settings, release, "compression", {"codecs": {
        "uint32": {"payload_bytes": 1048576, "artifact_bytes": 2 * 1048576, "median_lookup_decode_ms": 0.12},
        "vb": {"payload_bytes": 524288, "artifact_bytes": 1048576, "median_lookup_decode_ms": 0.30},
    }})
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/lab")
    method = page.get_by_role("row", name="TF-IDF", exact=False)
    expect(method.get_by_role("cell")).to_have_text(["—", "—", "—", "0.13", "2.13"])
    expect(page.get_by_text("Quality evaluation is pending", exact=False)).to_be_visible()
    expect(page.get_by_text("Highest measured nDCG@10", exact=False)).to_have_count(0)
    expect(page.get_by_text("Ranking quality by method", exact=False)).to_have_count(0)
    expect(page.get_by_text("Lowest measured median time", exact=False)).to_contain_text("TF-IDF")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    nav = page.get_by_role("navigation", name="IR Lab tabs")
    nav.get_by_role("link", name="Course experiments").click()
    row = page.get_by_role("row", name="Variable-byte", exact=False)
    expect(row.get_by_role("cell")).to_have_text(["0.50", "1.00", "50.0%", "0.30"])
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.go_back()
    expect(method.get_by_role("cell").nth(3)).to_have_text("0.13")

    response["quality"] = {"label_type": "AI-judged", "sample_counts": dict.fromkeys(LAB_METHODS, 8),
                           "aggregates": {key: {"nDCG@10": .6 + i * .04, "P@10": .4, "MRR@10": .5}
                                          for i, key in enumerate(LAB_METHODS)}}
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    expect(page.get_by_text("Highest measured nDCG@10", exact=False)).to_contain_text("Hybrid")
    expect(page.get_by_text("Ranking quality by method", exact=False)).to_be_visible()
    expect(method.get_by_role("cell")).to_have_text(["0.600", "0.400", "0.500", "0.13", "2.13"])
    response.update(release_id="a"*24, measurement=None, quality=None)
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    expect(page.get_by_text("No compatible measurements", exact=False)).to_be_visible()
    expect(method.get_by_role("cell")).to_have_text(["—", "—", "—", "—", "—"])
    expect(page.get_by_text("Lowest measured median time", exact=False)).to_have_count(0)
