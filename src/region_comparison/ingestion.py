"""Resumable BDL HTTP client with validated disk cache and bounded rate/retry budgets."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import pandas as pd

from region_comparison.validation import indicator_id, interpret_observation

DEFAULT_RATE_LIMITS = ((1, 1), (900, 90), (43200, 900), (604800, 9000))


class BDLError(RuntimeError):
    """A source request could not produce a verified response."""


class CacheIntegrityError(BDLError):
    """A cached response does not match its recorded hash."""


class PaginationError(BDLError):
    """An API result set is incomplete or duplicated."""


class RateLimitBudgetExceeded(BDLError):
    """The conservative request budget requires a later resumable run."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_bytes(path: Path, value: bytes) -> None:
    """Replace within one directory, tolerating brief Windows sharing violations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * 2**attempt)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except PermissionError:
            # A blocked temporary file is harmless; the previous destination remains intact.
            pass


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


class MultiWindowRateLimiter:
    """Sequential requests are bounded in seconds, minutes and a rolling 12-hour window."""

    def __init__(
        self,
        windows: tuple[tuple[float, int], ...] = DEFAULT_RATE_LIMITS,
        *,
        state_path: Path | None = None,
        max_wait: float = 65,
        clock: Any = time.time,
        sleep: Any = time.sleep,
    ) -> None:
        if not windows or any(seconds <= 0 or limit < 1 for seconds, limit in windows):
            raise ValueError("Rate windows require positive durations and request counts.")
        self.windows, self.state_path, self.max_wait = windows, state_path, max_wait
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self.events: list[float] = []
        if state_path and state_path.exists():
            try:
                self.events = [float(v) for v in json.loads(state_path.read_text())]
                if any(not math.isfinite(value) for value in self.events):
                    raise ValueError("Invalid request checkpoint timestamp")
            except (ValueError, TypeError, OSError) as exc:
                raise CacheIntegrityError("Rate-limit checkpoint is invalid.") from exc

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            maximum = max(seconds for seconds, _ in self.windows)
            self.events = [stamp for stamp in self.events if now - stamp < maximum]
            wait = 0.0
            for seconds, limit in self.windows:
                recent = [stamp for stamp in self.events if now - stamp < seconds]
                if len(recent) >= limit:
                    wait = max(wait, recent[-limit] + seconds - now + 0.001)
            if wait > self.max_wait:
                raise RateLimitBudgetExceeded(
                    f"Request budget exhausted; resume from cache after {math.ceil(wait)} seconds."
                )
            if wait > 0:
                self.sleep(wait)
            self.events.append(self.clock())
            if self.state_path:
                _atomic_json(self.state_path, self.events)


class BDLClient:
    """One-request-at-a-time API client; secrets exist only in the request header."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        base_url: str = "https://bdl.stat.gov.pl/api/v1/",
        client_id: str | None = None,
        timeout: float = 30,
        max_attempts: int = 4,
        transport: httpx.BaseTransport | None = None,
        rate_limits: tuple[tuple[float, int], ...] = DEFAULT_RATE_LIMITS,
        sleep: Any = time.sleep,
        clock: Any = time.time,
        jitter: Any = None,
        max_retry_wait: float = 120,
        rate_state_path: str | Path | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive.")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/") + "/"
        self.max_attempts, self.max_retry_wait = max_attempts, max_retry_wait
        self.sleep, self.clock = sleep, clock
        self.jitter = jitter or (lambda: random.uniform(0, 0.25))
        headers = {"Accept": "application/json", "User-Agent": "RegionComparison/0.1"}
        key = client_id or os.environ.get("GUS_API_KEY")
        if key:
            headers["X-ClientId"] = key
        self.http = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers=headers,
            transport=transport,
            follow_redirects=True,
        )
        self.limiter = MultiWindowRateLimiter(
            rate_limits,
            state_path=Path(rate_state_path)
            if rate_state_path
            else self.cache_dir / ".rate-state.json",
            sleep=sleep,
            clock=clock,
        )
        self.requests: list[dict[str, Any]] = []
        self.last_pagination: dict[str, Any] = {}

    def __enter__(self) -> BDLClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self.http.close()

    def _request_identity(
        self, endpoint: str, params: dict[str, Any] | None
    ) -> tuple[str, list, str]:
        if "://" in endpoint or endpoint.startswith("/"):
            raise ValueError("Use a relative BDL endpoint.")
        parameters = httpx.QueryParams(params or {})
        pairs = sorted(parameters.multi_items())
        if any(
            name.lower() in {"key", "token", "api_key", "clientid", "x-clientid"}
            for name, _ in pairs
        ):
            raise ValueError("API credentials must only be supplied in X-ClientId.")
        url = urljoin(self.base_url, endpoint)
        canonical = json.dumps({"url": url, "params": pairs}, separators=(",", ":"))
        return url, pairs, hashlib.sha256(canonical.encode()).hexdigest()

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None and (header := response.headers.get("Retry-After")):
            try:
                delay = float(header)
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(header)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    delay = max(0, parsed.timestamp() - self.clock())
                except (ValueError, TypeError, OverflowError):
                    delay = min(30, 2**attempt + self.jitter())
            if delay > self.max_retry_wait:
                raise RateLimitBudgetExceeded(
                    f"Source Retry-After requires {math.ceil(delay)} seconds; resume from cache later."
                )
            return delay
        return min(30, 2**attempt + self.jitter())

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url, pairs, cache_key = self._request_identity(endpoint, params)
        body_path = self.cache_dir / f"{cache_key}.json"
        meta_path = self.cache_dir / f"{cache_key}.meta.json"
        if body_path.exists() or meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if sha256_file(body_path) != meta["sha256"]:
                    raise ValueError("Hash mismatch")
                result = json.loads(body_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(result, dict)
                    or meta["url"] != url
                    or meta["params"] != [list(p) for p in pairs]
                ):
                    raise ValueError("Cache metadata mismatch")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CacheIntegrityError(
                    f"Corrupt BDL cache entry {cache_key}; remove this entry explicitly."
                ) from exc
            self.requests.append({**meta, "cache_hit": True, "cache_file": str(body_path)})
            return result
        for attempt in range(self.max_attempts):
            self.limiter.acquire()
            response = None
            try:
                response = self.http.get(url, params=pairs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == self.max_attempts:
                    raise BDLError(
                        f"BDL request failed after {self.max_attempts} attempts ({type(exc).__name__})."
                    ) from exc
                self.sleep(self._retry_delay(None, attempt))
                continue
            if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
                if attempt + 1 == self.max_attempts:
                    raise BDLError(
                        f"BDL returned HTTP {response.status_code} after {self.max_attempts} attempts."
                    )
                self.sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise BDLError(f"BDL returned permanent HTTP {response.status_code}.")
            media = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise BDLError(f"BDL response content type {media!r} is not JSON.")
            try:
                result = response.json()
            except ValueError as exc:
                raise BDLError("BDL returned malformed JSON.") from exc
            if not isinstance(result, dict) or "error" in result:
                raise BDLError("BDL response is not a successful JSON object.")
            _atomic_bytes(body_path, response.content)
            meta = {
                "url": url,
                "params": [list(p) for p in pairs],
                "retrieved_at": utc_now(),
                "sha256": sha256_file(body_path),
            }
            _atomic_json(meta_path, meta)
            self.requests.append({**meta, "cache_hit": False, "cache_file": str(body_path)})
            return result
        raise BDLError("Request retry budget exhausted.")

    def paginate(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        key: str = "results",
        page_size: int = 100,
        max_pages: int = 1000,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected: int | None = None
        page = 0
        while page < max_pages:
            response = self.get_json(
                endpoint, {**(params or {}), "page": page, "page-size": page_size}
            )
            batch = response.get(key)
            total = response.get("totalRecords")
            if not isinstance(batch, list) or not isinstance(total, int) or total < 0:
                raise PaginationError("Paged response lacks results or valid totalRecords.")
            if expected is None:
                expected = total
            elif total != expected:
                raise PaginationError("totalRecords changed during pagination.")
            if "page" in response and int(response["page"]) != page:
                raise PaginationError("The API repeated or returned an unexpected page.")
            for item in batch:
                if not isinstance(item, dict):
                    raise PaginationError("Paged records must be JSON objects.")
                identity = str(item.get("id", item.get("unitId", json.dumps(item, sort_keys=True))))
                if identity in seen:
                    raise PaginationError(f"Duplicate source record in pagination: {identity}.")
                seen.add(identity)
                records.append(item)
            if len(records) > expected:
                raise PaginationError("Received more records than totalRecords.")
            if len(records) == expected:
                self.last_pagination = {
                    "pages_expected": page + 1,
                    "pages_received": page + 1,
                    "records_expected": expected,
                    "records_received": len(records),
                }
                return records
            if not batch:
                raise PaginationError(
                    f"Incomplete download: expected {expected}, received {len(records)}."
                )
            page += 1
        raise PaginationError("Pagination exceeded the finite page budget.")


def fetch_snapshot(
    config: dict[str, Any], path: str | Path, client: BDLClient | None = None
) -> Path:
    """Fetch each selected indicator for all regional units/years, retaining source provenance."""
    from region_comparison.storage import load_snapshot
    from region_comparison.validation import validate_dataset

    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    manifest_path = path / "manifest.json"
    configuration_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("config_sha256") != configuration_hash:
            raise BDLError(
                "Existing snapshot belongs to a different configuration; choose a new directory."
            )
        if manifest.get("state") == "complete":
            report = validate_dataset(load_snapshot(path))
            if not report.valid:
                raise BDLError(
                    "Existing complete snapshot failed validation: " + "; ".join(report.errors)
                )
            return path
    else:
        manifest = {
            "snapshot_id": f"bdl-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{configuration_hash[:8]}",
            "manifest_schema_version": 1,
            "state": "partial",
            "started_at": utc_now(),
            "finished_at": None,
            "errors": [],
            "files": {},
            "config_sha256": configuration_hash,
            "code_version": "0.1.0",
            "config_version": config.get("config_version", "1"),
            "region_id": config.get("region_id", "030200000000"),
            "years": config["years"],
            "unit_ids": [str(u["bdl_unit_id"]) for u in config["units"]],
            "indicator_ids": [indicator_id(i) for i in config["indicators"]],
        }
    _atomic_json(manifest_path, manifest)
    own_client = client is None
    if client is None:
        from region_comparison.config import ROOT

        cache_root = ROOT / "data" / "raw" / "bdl-cache"
        namespace = hashlib.sha256(manifest["snapshot_id"].encode()).hexdigest()
        client = BDLClient(
            cache_root / "snapshots" / namespace, rate_state_path=cache_root / ".rate-state.json"
        )
    try:
        indicators, attributes, units = config["indicators"], config["attributes"], config["units"]
        selected_years = set(map(int, config["years"]))
        if any(
            not selected_years.issubset(set(map(int, unit.get("years", config["years"]))))
            for unit in units
        ):
            raise BDLError(
                "Selected years exceed the discovered unit registry; repeat source discovery."
            )
        if any(
            not selected_years.issubset(set(map(int, item.get("years", [])))) for item in indicators
        ):
            raise BDLError(
                "Selected years exceed the frozen definition contract; repeat source discovery."
            )
        live_units = client.paginate(
            "units",
            {"parent-id": manifest["region_id"], "level": 6, "format": "json", "lang": "pl"},
        )
        live_units_by_id = {str(unit["id"]): unit for unit in live_units}
        live_unit_pages = client.last_pagination["pages_received"]
        for unit in units:
            uid = str(unit["bdl_unit_id"])
            actual = live_units_by_id.get(uid)
            if actual is None or str(actual.get("kind")) != str(unit["kind"]):
                raise BDLError(f"Unit {uid} disappeared or changed kind; repeat source discovery.")
            if unit.get("parent_id") and str(actual.get("parentId")) != str(unit["parent_id"]):
                raise BDLError(f"Unit {uid} changed hierarchy; repeat source discovery.")
        _atomic_json(path / "source_responses" / "unit-registry.json", {"results": live_units})
        live_attributes = client.get_json("attributes", {"format": "json", "lang": "pl"})
        if not isinstance(live_attributes.get("results"), list):
            raise BDLError("The current source attribute dictionary is invalid.")
        by_attribute = {str(item["id"]): item for item in live_attributes["results"]}
        for item in attributes:
            if by_attribute.get(str(item["id"])) != item:
                raise BDLError(
                    "The source attribute dictionary changed; review its semantics before refresh."
                )
        attributes = live_attributes["results"]
        _atomic_json(path / "source_responses" / "attributes.json", live_attributes)
        for filename, contents in (
            ("units.json", units),
            ("indicators.json", indicators),
            ("attributes.json", attributes),
        ):
            _atomic_json(path / filename, contents)
        _atomic_json(
            path / "configuration.json",
            {
                key: config[key]
                for key in (
                    "config_version",
                    "region_id",
                    "region_name",
                    "years",
                    "unit_level",
                    "accepted_kinds",
                    "indicators",
                    "derived",
                )
                if key in config
            },
        )
        observations = []
        total_pages = total_records = 0
        for definition in indicators:
            iid = indicator_id(definition)
            metadata = client.get_json(f"variables/{iid}", {"format": "json", "lang": "pl"})
            expected_fields = {
                "subjectId": definition.get("subject_id"),
                "measureUnitId": definition.get("measure_unit_id"),
                "level": definition.get("level", 6),
                **definition.get("source_dimensions", {}),
            }
            if str(metadata.get("id")) != iid or any(
                str(metadata.get(key)) != str(value)
                for key, value in expected_fields.items()
                if value is not None
            ):
                raise BDLError(f"Source definition for {iid} changed; repeat source discovery.")
            if not selected_years.issubset(set(map(int, metadata.get("years", [])))):
                raise BDLError(f"Source variable {iid} does not cover every selected year.")
            _atomic_json(path / "source_responses" / f"variable-{iid}.json", metadata)
            params = {
                "unit-parent-id": manifest["region_id"],
                "unit-level": 6,
                "year": config["years"],
                "format": "json",
                "lang": "pl",
            }
            records = client.paginate(f"data/by-variable/{iid}", params)
            total_pages += client.last_pagination["pages_received"]
            total_records += client.last_pagination["records_received"]
            source_file = f"source_responses/data-{iid}.json"
            _atomic_json(
                path / source_file,
                {
                    "url": client.base_url + f"data/by-variable/{iid}",
                    "params": params,
                    "results": records,
                    **client.last_pagination,
                },
            )
            by_unit = {str(record["id"]): record for record in records}
            current_full_units = {
                uid
                for uid in by_unit
                if uid in live_units_by_id
                and str(live_units_by_id[uid].get("kind")) in {"1", "2", "3"}
            }
            if current_full_units != set(manifest["unit_ids"]):
                raise BDLError(
                    f"Variable {iid} has changed regional scope; repeat source discovery."
                )
            for unit in units:
                uid = str(unit["bdl_unit_id"])
                if uid not in by_unit:
                    raise PaginationError(
                        f"Required complete gmina {uid} missing from variable {iid} response."
                    )
                values = by_unit[uid].get("values", [])
                by_year = {int(v["year"]): v for v in values}
                if len(by_year) != len(values):
                    raise PaginationError(f"Repeated observation year for {uid}/{iid}.")
                for year in config["years"]:
                    value = by_year.get(int(year))
                    # An absent year in a fully retrieved unit result is source missingness.
                    raw, attr = (
                        (None, None)
                        if value is None
                        else (value.get("val"), str(value.get("attrId", "")))
                    )
                    observations.append(
                        {
                            "unit_id": uid,
                            "year": int(year),
                            "indicator_id": iid,
                            "raw_value": raw,
                            "raw_attr_id": attr,
                            **interpret_observation(raw, attr, attributes),
                            "source_file": source_file,
                            "source_record": f"{uid}/{year}",
                        }
                    )
        pd.DataFrame(observations).to_csv(path / "observations.csv", index=False, encoding="utf-8")
        manifest.update(
            state="complete",
            finished_at=utc_now(),
            errors=[],
            requests=client.requests,
            pages_expected=total_pages,
            pages_received=total_pages,
            records_expected=total_records,
            records_received=total_records,
            observation_count=len(observations),
            unit_count=len(units),
            metadata_page_count=live_unit_pages + 1 + len(indicators),
        )
        manifest["files"] = {
            str(file.relative_to(path)).replace("\\", "/"): sha256_file(file)
            for file in path.rglob("*")
            if file.is_file()
            and "cache" not in file.relative_to(path).parts
            and file.name != "manifest.json"
        }
        _atomic_json(manifest_path, manifest)
        report = validate_dataset(load_snapshot(path))
        if not report.valid:
            raise BDLError("Downloaded snapshot failed validation: " + "; ".join(report.errors))
        _atomic_json(path / "quality-report.json", report.to_dict())
        return path
    except Exception as exc:
        manifest.update(state="partial", finished_at=None)
        manifest["errors"] = [f"{type(exc).__name__}: {exc}"]
        _atomic_json(manifest_path, manifest)
        raise
    finally:
        if own_client:
            client.close()
