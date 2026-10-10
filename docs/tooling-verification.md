# Tooling verification

Local Python 3.12.10 and a new isolated environment were used. `pip check` confirmed the resolved dependency set. `requirements.lock` pins all direct/transitive development and runtime dependencies; it was installed on Windows and in the Debian-based Python container. No existing environment was copied.

The [checkout repository](https://github.com/actions/checkout) and [setup-python repository](https://github.com/actions/setup-python) document their current v7 actions. The workflow pins the actual v7 Git refs verified on 10 October 2026: checkout `3d3c42e5aac5ba805825da76410c181273ba90b1`; setup-python `5fda3b95a4ea91299a34e894583c3862153e4b97`. Actual workflow runs are required before treating CI as PASS.

Concrete image tags were pulled from the official registries: Python `3.12.10-slim-bookworm`, digest `sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db`; PostgreSQL `17.7-bookworm`, digest `sha256:86e0b703649d7a792bd9243ee28afc9d8f7c6b2b5638077c9d6882d4d472bbfd`. PostgreSQL 17.7 was verified through a real connection. See the [official PostgreSQL image](https://hub.docker.com/_/postgres).

Microsoft Edge is available locally; Playwright uses the installed browser for actual screenshots. It is optional for the demo. No synthetic screenshot or rendered mockup is used as verification.
