#!/usr/bin/env python3
"""Exercise an already running local release and save actual API/browser evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from techsearch.io import now, write_json

CASES = {
    "keyword": "Promise.all",
    "boolean": "source:mdn AND (title:CSS OR title:HTML) AND NOT title:SVG",
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
            if mode == "fuzzy":
                expansion = next(item for item in result["trace"]["expansions"]
                                 if item["kind"] == "fuzzy" and item["from"] == query.casefold())
                assert any(term == "promise.all" and weight > 0 for term, weight in expansion["terms"])
                corrected = next(hit for hit in result["results"] if "promise.all" in hit["evidence"]["matched_terms"])
                assert any(part["match"] and part["text"].casefold() == "promise.all" for part in corrected["snippet"])
            report["modes"][mode] = {"query": query, "total": result["total"], "timing_ms": result["timing_ms"],
                                     "top_id": result["results"][0]["id"], "trace": result["trace"]}
        existing = search("Promise.all", mode="fuzzy")
        assert existing["results"] and not existing["trace"]["expansions"]
        literal = next(hit for hit in existing["results"] if "promise.all" in hit["evidence"]["matched_terms"])
        assert any(part["match"] and part["text"].casefold() == "promise.all" for part in literal["snippet"])
        report["checks"]["fuzzy_evidence"] = {"corrected": "promsie.all", "literal": "Promise.all", "matched_term": "promise.all"}
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
        auto = search("wait for several JavaScript promises to finish")
        assert auto["mode"] == "hybrid" and "dense" in auto["trace"]["branches"] and not auto["trace"]["fallback"]
        for identifier in ("Promise.all", "querySelectorAll"):
            auto = search(identifier)
            assert auto["mode"] == "keyword" and auto["results"]
        report["checks"]["constraints_and_auto"] = "passed"
        first = search("CSS", mode="keyword", page_size=4)
        second = get(f'/search/{first["search_id"]}', params={"page": 2, "size": 4})
        assert first["total"] == second["total"] and first["total"] > 4
        assert not ({hit["id"] for hit in first["results"]} & {hit["id"] for hit in second["results"]})
        hit = first["results"][0]
        document = get("/documents/" + hit["id"])
        evidence = hit["evidence"]
        assert evidence and any(segment["ordinal"] == evidence["ordinal"] for segment in document["segments"])
        assert hit["snippet"] and document["metadata"]["raw_storage"] in {"raw", "legacy"}
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
        inventory = get("/report-inventory")
        assert inventory["active_release_id"] == ready["release_id"]
        lab = get("/lab")
        report["lab_measurement"] = (
            {key: lab["measurement"][key] for key in ("split", "query_count", "paired_queries")}
            if lab["measurement"] else None
        )
        compression = get("/reports/compression")
        assert compression["status"] in {"available", "build-only"}
        report["compression_status"] = compression["status"]
        report["compression_artifact_bytes"] = {codec: stats["artifact_bytes"]
                                                for codec, stats in compression["report"]["codecs"].items()}
        availability = {}
        for name in ("taat-daat", "graph", "latent", "retrieval", "ablations-dev"):
            value = get("/reports/" + name)
            assert value["release_id"] == ready["release_id"]
            assert value["status"] in {"available", "not-run"}
            availability[name] = value["status"]
        evaluation = get("/reports/evaluation-dev")
        assert evaluation["status"] in {"blocked", "partial", "available", "not-run"}
        if evaluation["status"] in {"blocked", "partial"}:
            assert "aggregates" not in evaluation["report"]
        report["evaluation_status"] = evaluation["status"]
        report["active_report_status"] = availability
        report["checks"]["saved_reports"] = "passed"

    from playwright.sync_api import expect, sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        external = []

        def only_app_requests(route):
            if route.request.url.startswith(base + "/"):
                route.continue_()
            else:
                external.append(urlsplit(route.request.url).hostname)
                route.abort()

        page.route("**/*", only_app_requests)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.screenshot(path=str(output / "search-home.png"), full_page=True)
        page.keyboard.press("/")
        field = page.get_by_label("Search the corpus", exact=True)
        expect(field).to_be_focused()
        field.fill("CSS grid")
        field.press("Enter")
        expect(page.locator("#results > li").first).to_be_visible(timeout=180000)
        page.screenshot(path=str(output / "search-desktop.png"), full_page=True)
        page.get_by_role("button", name="Next", exact=True).click()
        expect(page.locator("#status")).to_contain_text("Page 2 of 10")
        page.get_by_role("button", name="Preview", exact=True).first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.screenshot(path=str(output / "evidence.png"))
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "search-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(base + "/lab")
        nav = page.get_by_role("navigation", name="IR Lab tabs")
        expect(nav.get_by_role("link")).to_have_count(3)
        model_table = page.get_by_role("table", name="Retrieval methods")
        expect(model_table.get_by_role("row")).to_have_count(6)
        assert lab["release_id"] == ready["release_id"]
        if lab["measurement"]:
            expect(page.get_by_text("Median search time by method", exact=True)).to_be_visible()
            expect(model_table.get_by_role("row", name="BM25", exact=False)).to_contain_text(
                f'{lab["measurement"]["timing_ms"]["bm25"]["warm"]["p50"]:.2f}')
            page.get_by_text("Measurement details", exact=True).click()
            measurement_link = page.get_by_role("link", name="Export measurements")
            exported = page.request.get(base + measurement_link.get_attribute("href"))
            assert exported.ok and exported.json()["report"]["run_id"] == lab["measurement"]["run_id"]
            page.get_by_text("Measurement details", exact=True).click()
            if lab["quality"] and lab["quality"].get("status") in {"blocked", "partial"}:
                expect(page.get_by_text("Quality evaluation is pending", exact=False)).to_be_visible()
                expect(page.get_by_text("Ranking quality by method", exact=False)).to_have_count(0)
        if lab["quality"]:
            page.get_by_text("Relevance evaluation details", exact=True).click()
            quality_link = page.get_by_role("link", name="Export relevance evaluation")
            exported = page.request.get(base + quality_link.get_attribute("href"))
            assert exported.ok and exported.json()["report"] == lab["quality"]
            report["quality_export"] = {"split": lab["quality"]["split"], "pending": lab["quality"].get("pending"),
                                        "judged": lab["quality"].get("labeled"), "prompt": lab["quality"].get("prompt_version")}
        page.screenshot(path=str(output / "lab-model-comparison.png"), full_page=True, animations="disabled")
        nav.get_by_role("link", name="Try a query").click()
        page.locator("#method-a-method").select_option("dense")
        page.locator("#method-b-method").select_option("hybrid")
        conceptual = "wait for several JavaScript promises to finish"
        page.locator("#query").fill(conceptual)
        with page.expect_response(lambda response: response.url.endswith("/api/v1/compare"), timeout=180000) as comparison:
            page.get_by_role("button", name="Compare", exact=True).click()
        both = comparison.value.json()
        assert [both[side]["mode"] for side in ("left", "right")] == ["semantic", "hybrid"]
        assert all(both[side]["release_id"] == ready["release_id"] and len(both[side]["results"]) == 5 for side in both)
        report["lab_comparison"] = {"query": conceptual, "methods": {
            row["mode"]: {"time_ms": row["timing_ms"], "top_titles": [hit["title"] for hit in row["results"]]}
            for row in both.values()
        }}
        expect(page.locator("#status")).to_have_text("Comparison ready.")
        export_url = page.get_by_role("link", name="Export ranking").first.get_attribute("href")
        exported = page.request.get(base + export_url)
        assert exported.ok and exported.json()["release_id"] == ready["release_id"]
        page.get_by_role("button", name="Preview", exact=True).first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        page.screenshot(path=str(output / "lab-try-query.png"), full_page=True, animations="disabled")

        nav.get_by_role("link", name="Course experiments").click()
        compression_table = page.get_by_role("table", name="Index compression")
        expect(compression_table.get_by_role("row")).to_have_count(4)
        for name in ("Link authority", "Feedback", "LSI and K-means"):
            page.get_by_text(name, exact=True).click()
        expect(page.get_by_role("table", name="Link authority comparison")).to_be_visible()
        page.evaluate("window.scrollTo({ top: 0, behavior: 'instant' })")
        page.screenshot(path=str(output / "lab-course-experiments.png"), full_page=True, animations="disabled")
        page.go_back()
        expect(page.locator("#query")).to_have_value(conceptual)
        page.get_by_role("link", name="Search", exact=True).click()
        expect(page.get_by_label("Search the corpus", exact=True)).to_have_value("CSS grid")
        page.get_by_role("link", name="IR Lab").click()
        nav.get_by_role("link", name="Try a query").click()
        expect(page.locator("#query")).to_have_value(conceptual)
        page.set_viewport_size({"width": 390, "height": 844})
        nav.get_by_role("link", name="Model comparison").click()
        expect(model_table).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "lab-mobile.png"), animations="disabled")
        report["checks"]["lab_navigation_and_comparisons"] = "passed"
        assert not errors, errors
        assert not external, external
        report["browser"] = {"engine": browser.version, "modes": list(CASES), "javascript_errors": errors,
                              "blocked_external_requests": external,
                              "screenshots": sorted(path.name for path in output.glob("*.png"))}
        browser.close()
    write_json(output / "app-verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=Path("artifacts/execution/browser"))
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    result = verify(args.base_url.rstrip("/"), args.output, args.browser_executable)
    print(f"Verified release {result['release_id']}; evidence: {args.output}")
