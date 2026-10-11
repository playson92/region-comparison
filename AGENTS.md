# RegionComparison project instructions

Scope: Lower Silesia, public GUS BDL demographic and childcare data, Polish Streamlit UI. Do not expand to forecasting, all Poland, cloud hosting or accounts.

All project-created run artifacts must be inside project-root output/ and must never be tracked by Git. Use region_comparison.paths for ROOT, OUTPUT, unique run IDs and validated write paths. This includes caches, snapshots, exports, logs, test reports, screenshots and review archives. Maintained documentation and reproducible data/sample inputs remain versioned; browser downloads use the user's chosen destination. Do not change global Codex configuration.

Architecture: ingestion -> semantic validation -> immutable snapshot -> PostgreSQL or offline snapshot adapter -> metrics -> frozen regional cohort -> scoring/sensitivity -> UI/export. UI must reuse the analytical modules.

Use Python 3.12, src layout, Ruff (100 characters), pytest. Work on feature/fix branches with small English commits, update documentation, preserve user changes. Never commit secrets, raw caches, environments or private material. Source IDs, definitions, age groups, periods and attributes require actual GUS evidence. Missing data is never zero.

Commands from repository root: scripts/bootstrap.ps1; scripts/check.ps1; scripts/run-demo.ps1; python -m region_comparison doctor/discover/fetch/validate/load/report. PostgreSQL integration requires TEST_DATABASE_URL. Docker Compose provides migrations, immutable snapshot import and database-backed UI without live GUS requests on restart.

Delegation: source agent owns data/sample, config/indicators.yml and source discovery; pipeline agent owns ingestion/validation/storage/SQL and their tests; UI agent owns ui/app/theme/UI tests; primary owns analytics, integration, CLI, operations and remaining docs. Agree data interfaces before dependent implementation.

Definition of completion: verified 6-10 features, >=3 comparable source years, full regional cohort with manifest; immutable and idempotent imports; tested PostgreSQL and Docker path; offline clean-clone demo; honest missing/zero statuses; fixed-cohort weights, tie intervals and sensitivity; traceable export/findings; real screenshots; CI verified at PR head, independent agent review, authorized PR merge to main and verified release. A blocked criterion must remain explicitly BLOCKED/PARTIAL; never label skipped checks PASS.
