#!/usr/bin/env python3
"""Exercise an already running local release and save actual API/browser evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from techsearch.io import now, write_json

CASES = {
    "keyword": "Promise.all",
    "boolean": "source:mdn AND title:CSS",
    "phrase": '"Promise.all"',
    "prefix": "querySel*",
    "fuzzy": "promsie.all",
    "semantic": "run asynchronous tasks in parallel",
    "hybrid": "run asynchronous tasks in parallel",
    "field": "source:mdn title:CSS",
}


def verify(base, output, executable):
    report = {"created_at": now(), "base_url": base, "checks": {}, "modes": {}}
    with httpx.Client(base_url=base, timeout=180) as client:
        def get(path, **kwargs):
            reply = client.get("/api/v1" + path, **kwargs)
            reply.raise_for_status()
            return reply.json()

        def search(query, **options):
            reply = client.post("/api/v1/search", json={"query": query, **options})
            reply.raise_for_status()
            return reply.json()

        ready = get("/readiness")
        assert ready["dense_index"], ready
        report["release_id"] = ready["release_id"]
        for mode, query in CASES.items():
            result = search(query, mode=mode)
            assert result["results"] and not result["warnings"], (mode, result)
            assert result["mode"] == mode
            report["modes"][mode] = {"query": query, "total": result["total"], "timing_ms": result["timing_ms"],
                                     "top_id": result["results"][0]["id"], "trace": result["trace"]}
        for ranker in ("bm25", "tfidf"):
            a = search("CSS grid", mode="keyword", ranker=ranker, strategy="taat")
            b = search("CSS grid", mode="keyword", ranker=ranker, strategy="daat")
            c = search("CSS grid", mode="keyword", ranker=ranker, strategy="taat")
            signature = lambda result: [(hit["id"], hit["score"]) for hit in result["results"]]
            assert signature(a) == signature(b) == signature(c)
        report["checks"]["deterministic_rankers_and_taat_daat"] = "passed"
        for mode in ("keyword", "semantic", "hybrid", "auto"):
            constrained = search("CSS grid", mode=mode, source="mdn", topic="css")
            assert constrained["results"]
            assert all(hit["source"] == "mdn" and hit["topic"] == "css" for hit in constrained["results"])
            hard = search("source:mdn title:CSS", mode=mode)
            assert hard["results"] and all(hit["source"] == "mdn" for hit in hard["results"])
        for mode in ("semantic", "hybrid"):
            # Internal evaluation API accepts Boolean constraints explicitly;
            # public Auto must route them to the Boolean branch.
            constrained = search('source:mdn "Promise.all"', mode=mode)
            assert constrained["results"] and all(hit["source"] == "mdn" for hit in constrained["results"])
        auto = search("run asynchronous tasks in parallel")
        assert "dense" in auto["trace"]["branches"] and not auto["trace"]["fallback"]
        report["checks"]["constraints_and_auto"] = "passed"
        first = search("CSS", mode="keyword", page_size=4)
        second = get(f'/search/{first["search_id"]}', params={"page": 2, "size": 4})
        assert first["total"] == second["total"] and first["total"] > 4
        assert not ({hit["id"] for hit in first["results"]} & {hit["id"] for hit in second["results"]})
        hit = first["results"][0]
        document = get("/documents/" + hit["id"])
        evidence = hit["evidence"]
        assert evidence and any(segment["ordinal"] == evidence["ordinal"] for segment in document["segments"])
        assert hit["snippet"] and document["metadata"]["raw_storage"] == "legacy"
        # This automated UI/API intervention is not a relevance annotation.
        reply = client.post("/api/v1/feedback", json={"search_id": first["search_id"], "document": hit["id"], "value": 1})
        assert reply.status_code == 204
        refined = search("CSS", mode="keyword", apply_feedback=True)
        assert refined["trace"]["reranking"][0]["judgments"] == 1
        report["checks"]["pagination_evidence_feedback"] = "passed (automated interaction, no relevance assertion)"
        assert get("/suggestions", params={"q": "querySel"})["suggestions"]
        assert not search("zqqpzkx", mode="keyword")["results"]
        for query in ('title:"unterminated', "source:invalid", "alpha AND", ""):
            reply = client.post("/api/v1/search", json={"query": query})
            assert reply.status_code == 422, (query, reply.status_code)
        report["checks"]["suggestions_empty_invalid"] = "passed"
        compression = get("/reports/compression")
        assert compression["status"] == "available"
        report["measured_compression_bytes"] = {codec: stats["artifact_bytes"]
                                                  for codec, stats in compression["report"]["codecs"].items()}
        for name in ("taat-daat", "graph", "latent", "retrieval", "ablations-dev"):
            assert get("/reports/" + name)["status"] == "available", name
        evaluation = get("/reports/evaluation-dev")
        assert evaluation["status"] in {"blocked", "available"}
        if evaluation["status"] == "blocked":
            assert "aggregates" not in evaluation["report"]
        report["evaluation_status"] = evaluation["status"]
        report["checks"]["saved_reports"] = "passed"

    from playwright.sync_api import expect, sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.keyboard.press("/")
        field = page.get_by_label("Search the corpus", exact=True)
        expect(field).to_be_focused()
        field.fill("CSS grid")
        field.press("Enter")
        expect(page.locator("#results > li").first).to_be_visible(timeout=180000)
        page.screenshot(path=str(output / "search-desktop.png"), full_page=True)
        page.get_by_role("button", name="Next", exact=True).click()
        expect(page.get_by_text("Page 2 of 10", exact=True)).to_be_visible()
        page.get_by_role("button", name="View evidence").first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.screenshot(path=str(output / "evidence.png"))
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "search-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(base + "/lab")
        for mode, query in CASES.items():
            panels = page.locator("#configurations fieldset")
            panels.nth(0).get_by_label("Mode", exact=True).select_option(mode)
            panels.nth(1).get_by_label("Mode", exact=True).select_option(mode)
            page.locator("#query").fill(query)
            page.get_by_role("button", name="Compare", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("Comparison ready.", timeout=180000)
            expect(page.locator("#rankings .rank-panel")).to_have_count(2)
            expect(page.locator("#rankings .results").nth(0).locator("li").first).to_be_visible()
        page.screenshot(path=str(output / "lab-comparison.png"), full_page=True)
        page.get_by_role("button", name="Compression", exact=True).click()
        expect(page.locator("#report progress")).to_have_count(3)
        bars = page.locator("#report progress").evaluate_all("items => items.map(item => item.value)")
        assert sorted(bars) == sorted(report["measured_compression_bytes"].values())
        page.screenshot(path=str(output / "lab-compression.png"), full_page=True)
        if report["evaluation_status"] == "blocked":
            page.get_by_role("button", name="Dev metrics", exact=True).click()
            expect(page.locator("#report")).to_contain_text("Relevance evaluation is blocked")
        assert not errors, errors
        report["browser"] = {"engine": browser.version, "modes": list(CASES), "javascript_errors": errors,
                              "screenshots": sorted(path.name for path in output.glob("*.png"))}
        browser.close()
    write_json(output / "app-verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("artifacts/execution/browser"))
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    result = verify(args.base_url.rstrip("/"), args.output, args.browser_executable)
    print(f"Verified release {result['release_id']}; evidence: {args.output}")
