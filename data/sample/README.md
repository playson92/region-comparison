# Public GUS BDL demonstration snapshot

`bdl-dolnoslaskie-2023-2025-20261010-v0.1.1` covers **all 169 full Lower Silesian
municipalities**, **2023–2025**, and seven source variables. There are 3,549 source
observations. The source acquisition is complete, with no missing cells in this
particular snapshot. This does not imply that future GUS snapshots will be complete.

Source: Statistics Poland (GUS), Local Data Bank (BDL),
<https://bdl.stat.gov.pl/api/v1/>. Downloaded on 10 October 2026.
Public statistical data and accompanying GUS metadata are reused under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
The project's MIT license applies to code, including `build_sample.py`; it does not
replace the GUS data license. The semantic interpretations and locally calculated
metrics are the project's work, identified separately from source values.

- `observations.csv`: exact source values and attributes, interpreted values,
  quality status, and a pointer to each original response record.
- `units.json`: municipality codes, kinds, county hierarchy, and verified coverage.
  The 12-character BDL codes are strings. TERYT is deliberately NULL because no
  independent TERYT crosswalk was acquired.
- `indicators.json`: seven immutable source definitions.
- `attributes.json`: all 18 actual GUS attribute definitions.
- `configuration.json`: the exact source and derived indicator configuration.
- `manifest.json`: completion state, coverage, request provenance and SHA-256 hashes.
- `source-verification.json`: nine exact-age cross-checks, 507 ratio cross-checks,
  and yearly regional control totals.
- `source_responses/`: small, original UTF-8 JSON responses and request sidecars.
  Sidecars contain public URLs, structured parameters, HTTP status/content type,
  UTC retrieval time and SHA-256; no API key is stored.

The source dictionary also contains historical municipality records and urban/rural
parts. These remain in the evidence but are excluded from the analytical cohort.
The 169 municipalities consist of 35 urban, 76 rural and 58 urban-rural units.

`build_sample.py` reproduces the CSV, dictionaries, configuration and manifest from
the saved official responses. It performs **no network requests**:

```powershell
.\.venv\Scripts\python.exe .\data\sample\build_sample.py
```

Each reassembly creates a fresh snapshot identity and directory under
`output/snapshots/bdl-sample-<unique-run-id>/`. It preserves original response bytes
and their retrieval timestamps, checks source hashes, and records a new assembly
timestamp and the input snapshot identity. It also writes its own
`configuration.yml` in that output directory. An optional `--output` must name a
new directory inside project `output/`; existing directories are never overwritten.
The builder leaves the versioned sample and `config/indicators.yml` unchanged.
The application reads the packaged snapshot directly, so reassembly is unnecessary
for the demo.

The v0.1.1 packaged sample has a distinct identity because its maintained builder
and README changed. Observation values, attribute codes and retained GUS response
bytes are unchanged from the v0.1.0 demonstration snapshot. The original release
retains its original identity and file hashes.

This snapshot contains authentic zeros but no missing required values. A synthetic
missing-data demonstration must be clearly marked `DEMO_BRAK_DANYCH`, kept separate
from these files, and excluded from the official regional ranking.
