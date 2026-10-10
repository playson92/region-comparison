"""HTTP contracts run offline, including failure and resumable-cache paths."""

import json
from pathlib import Path

import httpx
import pytest
from pandas.testing import assert_series_equal

from region_comparison.ingestion import (
    BDLClient,
    BDLError,
    CacheIntegrityError,
    MultiWindowRateLimiter,
    PaginationError,
    RateLimitBudgetExceeded,
    fetch_snapshot,
)


@pytest.mark.parametrize("permanent", [False, True])
def test_atomic_checkpoint_retries_sharing_violation_without_losing_previous_file(
    tmp_path, monkeypatch, permanent
):
    from region_comparison.ingestion import _atomic_json

    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text('{"old": true}', encoding="utf-8")
    original_replace = Path.replace
    attempted_sources = []

    def replace(source, target):
        attempted_sources.append(source)
        if permanent or len(attempted_sources) == 1:
            raise PermissionError(5, "mock Windows sharing violation")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("region_comparison.ingestion.time.sleep", lambda _: None)
    if permanent:
        with pytest.raises(PermissionError):
            _atomic_json(checkpoint, {"new": True})
        assert json.loads(checkpoint.read_text()) == {"old": True}
        assert len(attempted_sources) == 5
    else:
        _atomic_json(checkpoint, {"new": True})
        assert json.loads(checkpoint.read_text()) == {"new": True}
        assert len(attempted_sources) == 2
    assert attempted_sources[0].name.startswith("checkpoint.json.")
    assert not list(tmp_path.glob("*.tmp"))


def make_client(tmp_path, handler, **kwargs):
    return BDLClient(
        tmp_path,
        transport=httpx.MockTransport(handler),
        rate_limits=((1, 10000), (60, 10000)),
        sleep=lambda _: None,
        jitter=lambda: 0,
        **kwargs,
    )


def test_real_saved_response_contract_and_structured_repeated_years(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "data" / "sample" / "source_responses"
    candidates = [
        file for file in sorted(sample.glob("data-*.json")) if not file.name.endswith(".meta.json")
    ]
    if not candidates:
        # This assertion is intentionally required: normal CI must contain real saved GUS replies.
        pytest.fail("The repository must bundle verified, real BDL data response fixtures.")
    original = json.loads(candidates[0].read_text(encoding="utf-8"))
    if "response" in original:
        original = original["response"]

    def handler(request):
        assert request.url.params.get_list("year") == ["2023", "2024", "2025"]
        assert request.url.params["page-size"] == "100"
        return httpx.Response(200, json=original)

    with make_client(tmp_path, handler) as client:
        reply = client.get_json(
            "data/by-variable/453371", {"year": [2023, 2024, 2025], "page-size": 100}
        )
    assert isinstance(reply["results"], list)
    assert reply["results"]
    assert isinstance(reply["results"][0]["id"], str)


@pytest.mark.parametrize("total", [0, 1, 2, 3, 4])
def test_complete_pagination_boundary_and_disk_resume(tmp_path, total):
    calls = []

    def handler(request):
        page = int(request.url.params["page"])
        calls.append(page)
        records = [{"id": str(i)} for i in range(page * 2, min(total, page * 2 + 2))]
        return httpx.Response(200, json={"results": records, "totalRecords": total})

    with make_client(tmp_path, handler) as client:
        result = client.paginate("units", page_size=2)
        assert len(result) == total
        assert client.last_pagination["records_received"] == total
    first_count = len(calls)
    with make_client(tmp_path, handler) as client:
        assert client.paginate("units", page_size=2) == result
    assert len(calls) == first_count


@pytest.mark.parametrize("failure", ["duplicate", "empty", "total_changes", "echo_wrong_page"])
def test_incomplete_or_repeated_page_is_rejected(tmp_path, failure):
    def handler(request):
        page = int(request.url.params["page"])
        if page == 0:
            return httpx.Response(200, json={"results": [{"id": "1"}], "totalRecords": 2})
        body = {"results": [{"id": "2"}], "totalRecords": 2}
        if failure == "duplicate":
            body["results"] = [{"id": "1"}]
        elif failure == "empty":
            body["results"] = []
        elif failure == "total_changes":
            body["totalRecords"] = 3
        else:
            body["page"] = 0
        return httpx.Response(200, json=body)

    with make_client(tmp_path, handler) as client, pytest.raises(PaginationError):
        client.paginate("units", page_size=1)


@pytest.mark.parametrize("failure", ["timeout", "429", "503", "invalid_retry_after"])
def test_retry_is_bounded_and_eventually_succeeds(tmp_path, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) > 1:
            return httpx.Response(200, json={"results": []})
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if failure in {"429", "invalid_retry_after"}:
            return httpx.Response(
                429, headers={"Retry-After": "2" if failure == "429" else "garbage"}
            )
        return httpx.Response(503)

    waits = []
    with make_client(tmp_path, handler) as client:
        client.sleep = waits.append
        assert client.get_json("attributes") == {"results": []}
    assert len(calls) == 2
    assert waits == ([2] if failure == "429" else [1])


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_4xx_is_never_retried(tmp_path, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with make_client(tmp_path, handler) as client, pytest.raises(BDLError, match="permanent"):
        client.get_json("units")
    assert len(calls) == 1


def test_persistent_429_and_large_retry_after_are_finite(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1"})

    with make_client(tmp_path, handler, max_attempts=3) as client, pytest.raises(BDLError):
        client.get_json("units")
    assert len(calls) == 3
    with make_client(
        tmp_path / "long", lambda _: httpx.Response(429, headers={"Retry-After": "9999"})
    ) as client:
        with pytest.raises(RateLimitBudgetExceeded):
            client.get_json("units")


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, text="<html>error</html>", headers={"content-type": "text/html"}),
        httpx.Response(200, text="broken", headers={"content-type": "application/json"}),
    ],
)
def test_non_json_never_enters_cache(tmp_path, reply):
    with make_client(tmp_path, lambda _: reply) as client, pytest.raises(BDLError):
        client.get_json("units")
    assert not list(tmp_path.glob("*.meta.json"))


def test_corrupt_cache_and_credentials_are_not_silently_accepted(tmp_path):
    secret = "test-secret-do-not-cache"

    def handler(request):
        assert request.headers["X-ClientId"] == secret
        return httpx.Response(200, json={"results": []})

    with make_client(tmp_path, handler, client_id=secret) as client:
        client.get_json("units")
        with pytest.raises(ValueError, match="credentials"):
            client.get_json("units", {"token": secret})
    for file in tmp_path.iterdir():
        assert secret not in file.read_text()
    cached = [
        p
        for p in tmp_path.glob("*.json")
        if not p.name.endswith("meta.json") and not p.name.startswith(".")
    ][0]
    cached.write_text("{}")
    with make_client(tmp_path, handler) as client, pytest.raises(CacheIntegrityError):
        client.get_json("units")


def test_multiwindow_budget_survives_restart(tmp_path):
    def clock():
        return 1000

    checkpoint = tmp_path / "rate.json"
    limiter = MultiWindowRateLimiter(
        ((1, 5), (60, 2), (43200, 3)), state_path=checkpoint, clock=clock, max_wait=0
    )
    limiter.acquire()
    limiter.acquire()
    resumed = MultiWindowRateLimiter(
        ((1, 5), (60, 2), (43200, 3)), state_path=checkpoint, clock=clock, max_wait=0
    )
    with pytest.raises(RateLimitBudgetExceeded):
        resumed.acquire()


def test_weekly_window_and_shared_budget_between_cache_namespaces(tmp_path):
    def clock():
        return 1000

    checkpoint = tmp_path / "shared-rate.json"
    for namespace in ("first", "second"):
        with BDLClient(
            tmp_path / namespace,
            rate_state_path=checkpoint,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []})),
            rate_limits=((1, 10), (900, 10), (43200, 10), (604800, 1)),
            clock=clock,
        ) as client:
            if namespace == "first":
                client.get_json("attributes")
            else:
                with pytest.raises(RateLimitBudgetExceeded):
                    client.get_json("attributes")


def _real_fixture_handler(sample: Path, calls: list):
    def handler(request):
        calls.append(str(request.url))
        endpoint = request.url.path.rsplit("/api/v1/", 1)[-1]
        if endpoint == "units":
            filename = f"units-page-{request.url.params['page']}.json"
        elif endpoint == "attributes":
            filename = "attributes.json"
        elif endpoint.startswith("variables/"):
            filename = f"variable-{endpoint.split('/')[-1]}.json"
        else:
            filename = f"data-{endpoint.split('/')[-1]}-page-{request.url.params['page']}.json"
        return httpx.Response(
            200,
            json=json.loads((sample / "source_responses" / filename).read_text(encoding="utf-8")),
        )

    return handler


def test_real_full_region_fetch_has_provenance_and_complete_snapshot_is_immutable(tmp_path):
    from region_comparison.config import read_indicators
    from region_comparison.storage import load_snapshot
    from region_comparison.validation import validate_dataset

    sample = Path(__file__).resolve().parents[1] / "data" / "sample"
    original = load_snapshot(sample)
    config = read_indicators()
    config.update(units=original.units.to_dict(orient="records"), attributes=original.attributes)
    calls = []
    target = tmp_path / "snapshot"
    with make_client(tmp_path / "cache", _real_fixture_handler(sample, calls)) as client:
        fetch_snapshot(config, target, client)
        first_manifest = (target / "manifest.json").read_bytes()
        count = len(calls)
        assert count == 32  # 3 unit pages + dictionary + 7 definitions + 21 observation pages.
        fetch_snapshot(config, target, client)
        assert len(calls) == count
        assert (target / "manifest.json").read_bytes() == first_manifest
    downloaded = load_snapshot(target)
    assert validate_dataset(downloaded).valid
    assert len(downloaded.units) == 169
    assert len(downloaded.observations) == 3549
    assert downloaded.manifest["pages_received"] == 21
    for column in ("raw_value", "raw_attr_id", "semantic_value", "quality_status", "reason_code"):
        key = ["unit_id", "year", "indicator_id"]
        left = original.observations.set_index(key).sort_index()[column]
        right = downloaded.observations.set_index(key).sort_index()[column]
        assert_series_equal(left, right, check_dtype=False, check_exact=True)


def test_partial_fetch_resumes_verified_pages_instead_of_repeating_requests(tmp_path):
    from region_comparison.config import read_indicators
    from region_comparison.storage import load_snapshot

    sample = Path(__file__).resolve().parents[1] / "data" / "sample"
    original = load_snapshot(sample)
    config = read_indicators()
    config.update(units=original.units.to_dict(orient="records"), attributes=original.attributes)
    calls = []
    good = _real_fixture_handler(sample, calls)
    fail_once = [True]

    def handler(request):
        if (
            "data/by-variable" in request.url.path
            and request.url.params["page"] == "1"
            and fail_once[0]
        ):
            fail_once[0] = False
            return httpx.Response(400)
        return good(request)

    target = tmp_path / "partial"
    with make_client(tmp_path / "cache", handler) as client:
        with pytest.raises(BDLError, match="permanent"):
            fetch_snapshot(config, target, client)
    checkpoint = json.loads((target / "manifest.json").read_text())
    assert checkpoint["state"] == "partial"
    started = checkpoint["started_at"]
    with make_client(tmp_path / "cache", handler) as client:
        fetch_snapshot(config, target, client)
    assert load_snapshot(target).manifest["started_at"] == started
    assert len(calls) == 32
