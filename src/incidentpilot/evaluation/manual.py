"""Narrow operator CLI for blinded manual benchmark workflow.

The CLI only addresses the configured Data service.  It has no database,
shell, or arbitrary-backend capability and never requests hidden ground truth.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

import httpx


def _client() -> httpx.Client:
    url = os.environ.get("INCIDENTPILOT_DATA_URL")
    token = os.environ.get("INCIDENTPILOT_INCIDENT_TOKEN")
    if not url or not token:
        raise RuntimeError("INCIDENTPILOT_DATA_URL and INCIDENTPILOT_INCIDENT_TOKEN are required")
    return httpx.Client(base_url=url.rstrip("/"), headers={"X-Incident-Token": token}, timeout=10)


def _print(response: httpx.Response) -> None:
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operate blinded IncidentPilot manual benchmarks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--participant", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("run_id", type=UUID)
    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("run_id", type=UUID)
    evidence.add_argument("evidence_ids", nargs="+", type=UUID)
    submit = subparsers.add_parser("submit")
    submit.add_argument("run_id", type=UUID)
    submit.add_argument("--root-cause", required=True)
    submit.add_argument("--affected-service", required=True)
    submit.add_argument("--failure-class", required=True)
    args = parser.parse_args(argv)

    try:
        with _client() as client:
            if args.command == "start":
                _print(
                    client.post(
                        "/v1/manual-benchmarks",
                        json={"participant_pseudonym": args.participant},
                    )
                )
            elif args.command == "inspect":
                _print(client.get(f"/v1/manual-benchmarks/{args.run_id}"))
            elif args.command == "evidence":
                _print(
                    client.post(
                        f"/v1/manual-benchmarks/{args.run_id}/evidence",
                        json=[str(item) for item in args.evidence_ids],
                    )
                )
            else:
                current = client.get(f"/v1/manual-benchmarks/{args.run_id}")
                current.raise_for_status()
                run = current.json()
                if run["finalized"]:
                    raise RuntimeError("manual run is already finalized")
                completed_at = datetime.now(UTC)
                run.update(
                    {
                        "completed_at": completed_at.isoformat(),
                        "duration_seconds": max(
                            0,
                            (
                                completed_at - datetime.fromisoformat(run["started_at"])
                            ).total_seconds(),
                        ),
                        "submitted_root_cause": args.root_cause,
                        "affected_service": args.affected_service,
                        "failure_class": args.failure_class,
                        "finalized": True,
                    }
                )
                _print(client.put(f"/v1/manual-benchmarks/{args.run_id}", json=run))
    except (httpx.HTTPError, RuntimeError) as error:
        print(f"manual benchmark operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
