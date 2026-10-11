# Data quality policy

The maintained demonstration input contains 169 full Lower Silesian municipalities in
2023–2025 and seven official source indicators. Its 3,549 observations include 2,484 admissible
nonzero values and 1,065 true zeros. These statements describe the packaged sample; they are
not assumptions about newly fetched snapshots.

Every observation preserves raw value, raw attribute, interpreted semantic value, quality
status, reason and exact source-record pointer. A zero is admissible only when supported by the
source value/attribute pair. Missing, unavailable, below-precision, preliminary, methodology and
scope flags retain their source meaning. Unknown attributes block activation. No value is imputed.

Source-record validation checks unit, year, indicator, raw value and attribute against the saved
response. Documented absent units or years require complete pagination proof; byte hashes alone
do not establish semantic correctness. Declared observed snapshot coverage describes availability,
not the date when a municipality began or ceased to exist.

Eligibility requires both score components in the particular year across the full region and
stays fixed for changes to weights and display selection. A missing profile-only feature does not
exclude the score. Fewer than two eligible units cannot produce scores or ranks.

The computed places-per-1000 ratio is compared with GUS indicator 1649860 at an absolute tolerance
of 0.500000001, reflecting integer rounding with a small numeric margin. Validation and the UI
show paired counts, maximum difference and exceedances. An exceedance requires investigation,
without automatically correcting either series or imputing missing values.

Generate actual run-specific counts, excluded cohorts and findings with
`python -m region_comparison report`. Results go to `output/reports/<run_id>/`.
Historical generated reports are preserved locally in
`output/codex_runs/legacy-v0_1_0/docs/`. DEMO_BRAK_DANYCH remains a clearly fictional,
separate UI example that never changes a real municipality or the official cohort.
