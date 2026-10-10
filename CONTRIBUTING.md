# Contributing

Use Python 3.12 and the committed dependency lock. Create feature/fix branches, keep English commits focused and run `scripts/check.ps1`. Run PostgreSQL integration with a dedicated `TEST_DATABASE_URL`, never a production database.

Changes to source definitions or analytical rules require a version change, explicit evidence, regression tests and refreshed documentation. Preserve immutable historical snapshots and raw value/attribute pairs. Never replace missing cells with zero or make eligibility depend on a display selection or weights.

Do not commit credentials, private data, environments or caches. Normal CI runs offline; live GUS access must remain explicit and rate limited. Review staged diffs and keep data source licensing separate from the MIT code license.
