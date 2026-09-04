# IncidentPilot

Phase 1, step 1: Python monorepo foundation for a real monitored multi-service
sandbox. **There is no running sandbox yet.** Service packages are namespaces,
not HTTP servers or queue consumers. No AI, chaos, remediation, memory, approval
engine, audit store, or evaluation behavior is implemented.

## Development

Requires Python 3.11+ (validated with 3.12). From the repository root:

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[api,data,worker,observability,dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

With GNU Make installed, `make install` and `make check` run the same steps using
the active Python. `PYTHON` can be overridden. Base installation includes only
shared configuration; extras separate API, persistence, workers, telemetry, and
development dependencies. Dependency ranges are compatibility bounds, not a
reproducible lock; a reviewed lock and container image digests remain required
before a reproducible sandbox deployment.

Settings read `INCIDENTPILOT_*` variables when constructed. `.env.example`
contains only safe values. A dotenv file is not loaded automatically; explicitly
use `Settings(_env_file=".env")` for local development. Unknown dotenv fields are
rejected. Only `local` and `test` environments are accepted at this stage.

Use `configure_logging(Settings())` at process startup and log through
`logging.getLogger("incidentpilot.<service>")`. Output is newline-delimited JSON
to stderr by default. Use static event names; messages are not automatically
redacted. Request bodies, tokens, credentials and sensitive exception text must
never be put in messages. This logger is not a tamper-evident audit system.

See [architecture](docs/architecture.md) for boundaries and remaining work,
and [infrastructure scope](infra/README.md) for the planned Compose stack.

