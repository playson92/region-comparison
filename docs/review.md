# Independent implementation review

Reviewed runtime commit: **`2d21fc963289993ed405ed96df46763d50746b9e`** (`feat/region-comparison-mvp`), 10 October 2026.

The reviewer was a separate implementation-review agent. This agent previously authored the GUS discovery, indicator configuration and committed source snapshot. The review is independent of the other agents' application, ingestion, database and analytical implementation; it is **not an independent endorsement of the reviewer's own source acquisition** and is not human acceptance.

## Outcome and scope

No unresolved high- or medium-severity implementation findings remain in the reviewed commit. The review covered ingestion completeness and refresh behavior, raw attribute interpretation, validation, transactional PostgreSQL storage, adapter equivalence, derived measures, scoring, sensitivity, export replay, CLI error handling, Streamlit behavior, Docker, CI and Windows scripts. It combined code inspection, controlled failure reproductions, regression tests and read-only checks of the running demonstration database.

The immutable source snapshot was not changed during this review. Later evidence-only documentation commits do not extend the reviewed runtime scope; a later runtime change requires another review.

## Findings resolved before the reviewed commit

| Severity | Location | Reproduction or consequence | Resolution verified |
| --- | --- | --- | --- |
| High | `src/region_comparison/ingestion.py`, default rate limiter | The former anonymous-client limits could exceed verified BDL time windows. | Conservative second, 15-minute, 12-hour and 7-day windows use a shared persisted request history. |
| High | `src/region_comparison/ingestion.py`, cache namespace | A fetch into a new snapshot directory could reuse an old response indefinitely through a shared URL cache. | New snapshots have separate cache namespaces; resuming the same snapshot retains its cache. Regression tests distinguish refresh from resume. |
| High | `src/region_comparison/ingestion.py`, territorial completeness | A fully retrieved response omitting one registered municipality incorrectly failed as an incomplete territorial scope. | A verified complete page set can produce explicit missing cells for an absent registered municipality or year, with null raw value and attribute and explicit omission provenance. An extra full municipality, changed kind, or missing pagination content still fails. |
| High | `src/region_comparison/metrics.py`, source contracts | Changing population reference period or facility scope could silently combine incompatible measures. | All seven source definitions are checked for their relevant age, facility, sex, period, unit and territorial dimensions before calculations. Controlled definition drift now fails. |
| Medium | `src/region_comparison/scoring.py`, weight normalization | Two finite weights of `1e308` overflowed their sum and became zero weights. | Scaling by the largest weight precedes normalization; finite extreme inputs now produce the expected equal weights. |
| Medium | `src/region_comparison/exports.py`, replay identity | Reusing a snapshot ID with changed data could replay a JSON scenario against different observations. | Replay checks the manifest, canonical adapter-independent content fingerprint, analytical definitions and exact reference cohort. Altered observations are rejected. |
| Medium | `src/region_comparison/exports.py`, export definitions | The scenario omitted derived formulas; source CSV rows omitted important unit and definition metadata. | JSON includes derived definitions and policies; CSV rows include metric identity, original source name, unit, definition and reference period. |
| Medium | `src/region_comparison/storage.py`, reactivation | Loading snapshot A, then B, then the identical A left B active while the CLI reported A as active. | Idempotent reimport transactionally reactivates the matching complete snapshot. PostgreSQL regression tests verify the active snapshot. |
| Medium | `src/region_comparison/storage.py`, metadata and null parity | Empty metadata strings changed to null in PostgreSQL, so genuine offline and database adapters had different fingerprints. Missing raw cells also needed adapter normalization. | Nested metadata preserves empty strings; absent raw values and attributes remain null. Full real-snapshot and controlled omission tests verify equal fingerprints, metrics, cohorts and replay results. |
| Medium | `src/region_comparison/ui.py`, analytical error boundary | A structurally valid but analytically incompatible snapshot could expose a Streamlit exception. | Analytical loading failures are caught and shown as Polish user-facing errors; UI regression coverage was added. |
| Medium | Screenshot capture and `docs/images/*` | Early images captured loading placeholders rather than populated analytical tables. | Final capture waits for actual chart marks and data rows. Final desktop, weights and mobile images were inspected. |

The missing-unit regression uses an otherwise complete paginated response and removes a whole municipality; its three cells remain missing rather than fabricated zero. The contrasting truncated-pagination case remains inactive. The committed public data has no authentic missing observations, so these controlled tests are explicitly distinguished from source evidence.

## Checks performed by this reviewer

On the exact runtime commit, the focused test command was:

```powershell
$env:TEST_DATABASE_URL = '<local dedicated region_test database URL>'
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_ingestion.py tests/test_analytics.py tests/test_storage.py
```

Result: **60 passed, 0 failed, 0 skipped**, in 13.67 seconds, including the six PostgreSQL integration tests. Tests used the dedicated `region_test` database, not the active demonstration database. `ruff check .` passed, and `ruff format --check .` reported all 34 Python files formatted. No new live GUS requests were made during final review.

Read-only verification of the active database at `127.0.0.1:55432/region_comparison` against `data/sample` confirmed:

- 169 full municipalities and 3,549 source observations;
- identical snapshot manifests and canonical dataset fingerprints;
- identical replayed scores when an offline-exported scenario was replayed through the PostgreSQL adapter.

The reviewer inspected [`comparison.png`](images/comparison.png), [`weights.png`](images/weights.png) and [`mobile.png`](images/mobile.png). Tables and charts are populated, weight changes are reflected in the displayed values, and the mobile view shows usable vertically arranged cards and charts. The supplied [`browser-check.json`](images/browser-check.json) records zero page exceptions, zero failed requests, three data rows in the comparison table, actual marks in all checked charts, and the equal-weight versus 80/20 scores. This is inspection of the captured evidence; the final browser automation itself was run by the implementation team.

## Team evidence and remaining publication gate

The implementation team reported the full `scripts/check.ps1 -Postgres` result on the same runtime commit as **89 passed, 0 failed, 0 skipped**, including ten UI tests and six PostgreSQL tests. It also reported a successful fresh real-API download through the implemented client, Docker and clean-clone checks. Those end-to-end executions were not rerun by this reviewer; their detailed evidence belongs in [`verification-results.json`](verification-results.json) and [`implementation-status.md`](implementation-status.md).

The team reported all four GitHub Actions jobs passing for the reviewed runtime commit in [PR CI run 38084763674](https://github.com/playson92/region-comparison/actions/runs/38084763674). This report does not claim approval for a later commit. Publication still requires the implementation team to check CI on the exact final PR head after recording the final evidence, then merge and tag the tested result as requested.

The score remains a relative demonstration based on capacity and demographics. It does not measure unmet demand, prices, queues or travel between municipalities. The review found no basis to present it as an investment recommendation or to treat counts of sensitivity scenarios as probabilities.
