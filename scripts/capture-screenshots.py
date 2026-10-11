"""Capture rendered charts and verify real interactions using installed Edge."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from region_comparison.paths import artifact_path, output_path, run_id


def wait_for_charts(page, expected: int) -> dict:
    """Cold chart chunks and charts below the fold must finish before capture."""
    panel = page.locator('[role="tabpanel"]:visible')
    charts = panel.locator('[data-testid="stPlotlyChart"]')
    charts.first.wait_for(timeout=45000)
    assert charts.count() == expected, f"Expected {expected} visible-tab charts"
    counts = []
    for chart in charts.all():
        chart.scroll_into_view_if_needed()
        chart.locator(".js-plotly-plot .main-svg").first.wait_for(state="visible", timeout=45000)
        points = chart.locator(".barlayer .point path, .scatterlayer .points path")
        points.first.wait_for(state="visible", timeout=45000)
        counts.append(points.count())
    return {"charts": len(counts), "data_marks": counts}


def wait_for_dataframes(page, expected: int) -> dict:
    """Wait for actual canvas pixels and rows, including tables below the fold."""
    frames = page.locator('[role="tabpanel"]:visible [data-testid="stDataFrame"]:visible')
    frames.first.wait_for(timeout=45000)
    assert frames.count() == expected, f"Expected {expected} visible-tab dataframes"
    rows = []
    for frame in frames.all():
        frame.scroll_into_view_if_needed()
        canvas = frame.locator('canvas[data-testid="data-grid-canvas"]').first
        canvas.wait_for(state="visible", timeout=45000)
        page.wait_for_function(
            """canvas => {
                if (canvas.width < 100 || canvas.height < 50) return false;
                const probe = document.createElement('canvas');
                probe.width = canvas.width;
                probe.height = canvas.height;
                const context = probe.getContext('2d', {willReadFrequently: true});
                context.drawImage(canvas, 0, 0);
                const pixels = context.getImageData(0, 0, probe.width, probe.height).data;
                const colors = new Set();
                for (let i = 0; i < pixels.length; i += 64) {
                    colors.add(`${pixels[i]},${pixels[i+1]},${pixels[i+2]},${pixels[i+3]}`);
                    if (colors.size >= 16) return true;
                }
                return false;
            }""",
            arg=canvas.element_handle(),
            timeout=30000,
        )
        grid = canvas.locator('[role="grid"]')
        row_count = int(grid.get_attribute("aria-rowcount"))
        assert row_count >= 2, "Screenshot table must contain source data rows"
        rows.append(row_count - 1)
    return {"tables": len(rows), "data_rows": rows}


def capture_content(page, path: Path, width: int, initial_height: int, tables: int) -> dict:
    """Expand the browser viewport to include Streamlit's native scroll container."""
    page.set_viewport_size({"width": width, "height": initial_height})
    main = page.locator('[data-testid="stMain"]')
    rendered_tables = wait_for_dataframes(page, tables)
    main.evaluate("element => element.scrollTop = 0")
    for _ in range(3):
        height = main.evaluate("element => element.scrollHeight")
        if height <= page.viewport_size["height"]:
            break
        page.set_viewport_size({"width": width, "height": min(height + 80, 6000)})
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    page.wait_for_timeout(700)
    wait_for_dataframes(page, tables)
    main.evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(path), full_page=True)
    return {
        "width": width,
        "height": page.viewport_size["height"],
        "rendered_dataframes": rendered_tables,
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8503")
    parser.add_argument("--output", type=Path, help="Screenshot directory inside project output")
    parser.add_argument("--run-id", help="Reuse the identifier of the current verification run")
    args = parser.parse_args(argv)
    try:
        args.run_id = run_id(args.run_id)
        args.output = output_path(
            args.output or artifact_path("codex_runs", args.run_id, "screenshots")
        )
    except ValueError as error:
        parser.error(str(error))
    return args


def main():
    args = _arguments()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        errors, failed_requests, console_messages = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {
                    "url": request.url,
                    "reason": request.failure,
                }
            ),
        )
        page.on(
            "console",
            lambda message: (
                console_messages.append(
                    {
                        "type": message.type,
                        "text": message.text,
                    }
                )
                if message.type in {"warning", "error"}
                else None
            ),
        )
        checks = {}
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            comparison = page.get_by_role("tab", name="Porównanie gmin", exact=True)
            comparison.wait_for(timeout=60000)
            comparison.click()
            checks["comparison"] = wait_for_charts(page, 2)
            initial_scores = page.locator(
                '[data-testid="stMetricValue"]:visible'
            ).all_text_contents()
            sizes = {
                "comparison": capture_content(page, args.output / "comparison.png", 1440, 1100, 1)
            }
            page.get_by_role("tab", name="Wagi i wrażliwość", exact=True).click()
            page.get_by_role("button", name="Akcent na podaż", exact=True).click()
            page.get_by_text(re.compile(r"Zastosowane wagi:.*80,0%.*20,0%")).wait_for(timeout=30000)
            checks["weights"] = wait_for_charts(page, 1)
            sizes["weights"] = capture_content(page, args.output / "weights.png", 1440, 1100, 4)
            comparison.click()
            checks["weighted_comparison"] = wait_for_charts(page, 2)
            weighted_scores = page.locator(
                '[data-testid="stMetricValue"]:visible'
            ).all_text_contents()
            assert len(initial_scores) == 3 and initial_scores != weighted_scores
            page.get_by_role("tab", name="Profil i trendy", exact=True).click()
            checks["profile"] = wait_for_charts(page, 1)
            sizes["profile"] = capture_content(page, args.output / "profile.png", 1440, 1100, 2)
            page.get_by_text("Scenariusz testowy: brak wymaganej miary", exact=True).click()
            page.get_by_text("Pokaż DEMO_BRAK_DANYCH", exact=True).click()
            missing = page.get_by_text(
                "DEMO_BRAK_DANYCH · Brak oceny · brak wymaganej liczby dzieci 0–2.", exact=True
            )
            missing.wait_for(timeout=30000)
            checks["missing_demo"] = {"explicit_fictional_identity": missing.inner_text()}
            sizes["missing_demo"] = capture_content(
                page, args.output / "missing-demo.png", 1440, 1100, 2
            )
            page.get_by_role("tab", name="Dane i metodologia", exact=True).click()
            page.get_by_text("Kontrola wskaźnika miejsc na 1000 dzieci", exact=True).wait_for()
            sizes["methodology"] = capture_content(
                page, args.output / "methodology.png", 1440, 1100, 2
            )
            export_dir = artifact_path("exports", args.run_id)
            export_dir.mkdir(parents=True, exist_ok=True)
            downloads = {}
            for label, filename in (
                ("Pobierz dane CSV", "browser-data.csv"),
                ("Pobierz konfigurację JSON", "browser-config.json"),
            ):
                with page.expect_download(timeout=30000) as pending:
                    page.get_by_text(label, exact=True).click()
                destination = export_dir / filename
                pending.value.save_as(str(destination))
                assert destination.stat().st_size > 0
                downloads[filename] = str(destination)
            config = json.loads((export_dir / "browser-config.json").read_text(encoding="utf-8"))
            assert len(config["selected_ids"]) == 3
            assert config["weights"] == {"places_per_1000": 0.8, "children_share_pct": 0.2}
            checks["browser_exports"] = {
                "files": downloads,
                "snapshot_id": config["snapshot_id"],
                "dataset_sha256": config["dataset_sha256"],
                "year": config["year"],
                "selected_ids": config["selected_ids"],
                "weights": config["weights"],
            }
            comparison.click()
            sidebar = page.locator('[data-testid="stSidebarCollapseButton"] button')
            if sidebar.is_visible():
                sidebar.click()
            page.set_viewport_size({"width": 480, "height": 1000})
            checks["mobile"] = wait_for_charts(page, 2)
            sizes["mobile"] = capture_content(page, args.output / "mobile.png", 480, 1000, 1)
            exception_count = page.locator('[data-testid="stException"]').count()
            local_failures = [
                request
                for request in failed_requests
                if urlsplit(request["url"]).hostname == urlsplit(args.url).hostname
                and request["reason"] != "net::ERR_ABORTED"
            ]
            result = {
                "url": args.url,
                "run_id": args.run_id,
                "output": str(args.output),
                "page_errors": errors,
                "exceptions": exception_count,
                "failed_requests": failed_requests,
                "local_request_failures": local_failures,
                "console_messages": console_messages,
                "browser": "Microsoft Edge / Playwright",
                "viewports": sizes,
                "rendered_chart_checks": checks,
                "baseline_scores": initial_scores,
                "supply_preset_scores": weighted_scores,
            }
            (args.output / "browser-check.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            assert not errors and exception_count == 0 and not local_failures, result
            print(json.dumps(result, ensure_ascii=True))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
