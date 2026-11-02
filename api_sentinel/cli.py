"""Command-line interface for API Sentinel."""

from __future__ import annotations

import argparse
import os
import sys
import time

from .config import MonitorConfig
from .engine import ProbeExecutor
from .mock_server import MockServerDaemon
from .models import HealthStatus
from .reporter import HtmlReporter, JsonReporter, TerminalReporter
from .storage import SentinelStorage


def cmd_init(args: argparse.Namespace) -> int:
    """Generate a starter sentinel configuration file."""
    output_path = args.output
    if os.path.exists(output_path) and not args.force:
        print(f"Error: Target file '{output_path}' already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    sample_config = {
        "name": "API Sentinel Default Monitor",
        "environment": "staging",
        "db_path": ".sentinel/sentinel.db",
        "concurrency": 4,
        "targets": [
            {
                "id": "health-check",
                "name": "Primary Service Health",
                "url": "https://httpbin.org/status/200",
                "method": "GET",
                "timeout_seconds": 5.0,
                "max_retries": 1,
                "sla_latency_threshold_ms": 500.0,
                "assertions": [
                    {"rule_type": "status_code", "expected": 200, "operator": "eq"},
                    {"rule_type": "max_latency_ms", "expected": 500.0, "operator": "lte"}
                ]
            }
        ]
    }
    config = MonitorConfig.from_dict(sample_config)
    config.save_to_file(output_path)
    print(f"Initialized new Sentinel configuration at: {output_path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Execute synthetic probes against configured targets."""
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found. Run 'api-sentinel init' first.", file=sys.stderr)
        return 1

    try:
        config = MonitorConfig.load_from_file(config_path)
    except Exception as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 1

    storage = SentinelStorage(config.db_path) if not args.no_db else None
    executor = ProbeExecutor(storage=storage)

    results = executor.probe_all(config.targets, concurrency=config.concurrency)

    # Generate metrics for targets
    metrics = None
    if storage:
        metrics = [
            storage.get_target_metrics(t.id, t.name)
            for t in config.targets
        ]

    # Handle output format
    fmt = args.format.lower()
    if fmt == "terminal":
        print(TerminalReporter.render_probe_summary(results, metrics))
    elif fmt == "json":
        incidents = storage.get_open_incidents() if storage else None
        output_str = JsonReporter.render(results, metrics, incidents)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_str)
            print(f"Wrote JSON report to: {args.output}")
        else:
            print(output_str)
    elif fmt == "html":
        incidents = storage.get_open_incidents() if storage else None
        html_out = HtmlReporter.render(config.name, results, metrics, incidents)
        target_file = args.output or "sentinel-report.html"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(html_out)
        print(f"Generated standalone HTML report: {target_file}")

    # Check failure gate
    has_unhealthy = any(r.status == HealthStatus.UNHEALTHY for r in results)
    if args.fail_on_unhealthy and has_unhealthy:
        return 2

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate historical SLA report from SQLite database."""
    db_path = args.db_path
    if not os.path.exists(db_path):
        print(f"Error: Database '{db_path}' not found.", file=sys.stderr)
        return 1

    storage = SentinelStorage(db_path)
    recent_probes = storage.get_recent_probes(limit=args.limit)
    incidents = storage.get_open_incidents()

    fmt = args.format.lower()
    if fmt == "html":
        html_out = HtmlReporter.render("Historical SLA Report", recent_probes, None, incidents)
        out_file = args.output or "sla-report.html"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html_out)
        print(f"Generated historical report: {out_file}")
    elif fmt == "json":
        json_out = JsonReporter.render(recent_probes, None, incidents)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_out)
            print(f"Wrote JSON report to: {args.output}")
        else:
            print(json_out)
    else:
        print(TerminalReporter.render_probe_summary(recent_probes))

    return 0


def cmd_serve_mock(args: argparse.Namespace) -> int:
    """Launch embedded mock server for testing."""
    host = args.host
    port = args.port
    daemon = MockServerDaemon(host=host, port=port)
    daemon.start()
    print(f"API Sentinel Mock Server running on {daemon.base_url}")
    print("Press Ctrl+C to terminate.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping mock server...")
        daemon.stop()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="api-sentinel",
        description="Autonomous synthetic API health, latency, and SLA reliability monitoring engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Bootstrap a new Sentinel configuration file")
    p_init.add_argument("-o", "--output", default="sentinel.json", help="Path to write configuration file")
    p_init.add_argument("-f", "--force", action="store_true", help="Overwrite existing configuration file")

    # check
    p_check = subparsers.add_parser("check", help="Probe endpoints and assert health status")
    p_check.add_argument("-c", "--config", default="sentinel.json", help="Path to sentinel configuration file")
    p_check.add_argument("--format", choices=["terminal", "json", "html"], default="terminal", help="Report format")
    p_check.add_argument("-o", "--output", help="Output file path (for html/json formats)")
    p_check.add_argument("--fail-on-unhealthy", action="store_true", help="Exit with non-zero code if targets fail")
    p_check.add_argument("--no-db", action="store_true", help="Do not persist results to SQLite database")

    # report
    p_report = subparsers.add_parser("report", help="Generate historical audit reports")
    p_report.add_argument("--db-path", default=".sentinel/sentinel.db", help="Path to SQLite database")
    p_report.add_argument("--limit", type=int, default=50, help="Number of recent records to process")
    p_report.add_argument("--format", choices=["terminal", "json", "html"], default="html", help="Report format")
    p_report.add_argument("-o", "--output", help="Output report file path")

    # serve-mock
    p_mock = subparsers.add_parser("serve-mock", help="Start local mock server for testing")
    p_mock.add_argument("--host", default="127.0.0.1", help="Bind host")
    p_mock.add_argument("--port", type=int, default=8080, help="Port to listen on")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "report":
        return cmd_report(args)
    if args.command == "serve-mock":
        return cmd_serve_mock(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
