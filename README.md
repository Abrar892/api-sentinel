# API Sentinel 🛡️

**Autonomous Synthetic API Health, Latency, and SLA Reliability Monitor**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-29%20passed-brightgreen.svg)]()
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-success.svg)]()
[![Version](https://img.shields.io/badge/version-0.2.0-indigo.svg)]()

---

## 📌 Problem Statement

Modern microservices, APIs, and distributed architectures often fail silently or experience latency spikes without triggering traditional process crashes. Heavyweight enterprise monitoring solutions (such as Datadog, Dynatrace, or self-hosted Prometheus/Grafana stacks) introduce substantial infrastructure overhead, complex agent setups, steep pricing tiers, and vendor lock-in.

Developers and DevOps engineers need a **lightweight, dependency-free, synthetic monitoring engine** that can:
1. Act as a **CI/CD Quality Gate** to block broken deployments.
2. Periodically audit critical HTTP/REST endpoints with deep payload assertions.
3. Track latency percentiles ($p50$, $p95$, $p99$) and SLA degradation over time using local persistent storage.
4. Generate self-contained, responsive **HTML status dashboards** and machine-readable JSON metrics without requiring external cloud accounts or internet CDNs.

**API Sentinel** is built to solve this problem with modern Python 3, zero third-party dependencies, high-resolution performance counters, and an embedded SQLite time-series engine.

---

## ✨ Features

- **⚡ Zero External Dependencies:** Runs anywhere Python 3.10+ is installed using standard library modules (`urllib`, `sqlite3`, `socket`, `ssl`, `concurrent.futures`, `dataclasses`, `http.server`).
- **🎯 Multi-Target Concurrent Probing:** Probes dozens of HTTP, HTTPS, and WebSocket (`ws://`, `wss://`) endpoints concurrently with configurable worker pools and per-target timeouts.
- **🔌 RFC 6455 WebSocket Monitoring:** Native support for WebSocket upgrade handshakes, Sec-WebSocket-Key / Accept verification, Ping/Pong latency tracking, and custom payload frame assertions without third-party libraries.
- **🔔 Webhook Incident Alerting:** Automatic real-time JSON alert dispatch to Slack, Discord, or custom webhook URLs upon target downtime or recovery.
- **🔍 Deep Assertion Engine:**
  - Status code validation (`eq`, `ne`, `lt`, `lte`, `gt`, `gte`).
  - High-precision latency threshold enforcement (millisecond resolution).
  - Dot-notation JSONPath payload assertions (e.g. `data.users.0.email`).
  - Response header pattern matching (case-insensitive).
  - Regex and substring search across response bodies.
- **📈 SLA & Latency Percentiles:** Tracks uptime percentages and calculates exact $p50$, $p95$, and $p99$ response times using linear interpolation.
- **🚨 Intelligent State Tracking:**
  - `HEALTHY`: All assertions passed within SLA latency bounds.
  - `DEGRADED`: Service is reachable with HTTP 2xx / WS 101 but latency violates SLA thresholds.
  - `UNHEALTHY`: Network unreachable, HTTP 5xx errors, or assertion failures.
  - Auto-manages incident lifecycles (opening on failure, resolving on recovery).
- **📊 Multi-Format Reporting:**
  - **Terminal Table:** ANSI-colored real-time CLI table with failure breakdowns.
  - **Standalone HTML Dashboard:** Clean, responsive dark-mode report with inline SVG latency distribution graphs and audit tables.
  - **Structured JSON:** Standardized output for automated ingestion and CI/CD artifact storage.
- **🧪 Embedded Simulation Server:** Built-in multi-behavior mock server simulating fast, delayed, and crashing endpoints for local verification and test automation.

---

## 🏗️ Project Architecture

```
api-sentinel/
├── api_sentinel/
│   ├── __init__.py           # Package exports and semantic versioning
│   ├── alerts.py             # Webhook incident notification dispatcher
│   ├── assertions.py         # Rule evaluation engine (JSONPath, regex, headers)
│   ├── cli.py                # Command-line entry points and argument parsing
│   ├── config.py             # Schema definition, model validation, and loaders
│   ├── engine.py             # Concurrent worker pool, WebSocket routing, and retry loop
│   ├── http_client.py        # Urllib client with high-resolution latency timing
│   ├── mock_server.py        # Embedded HTTP mock server for offline simulation
│   ├── models.py             # Dataclass domain entities and status enums
│   ├── reporter.py           # Terminal, JSON, and standalone SVG HTML generator
│   ├── storage.py            # SQLite time-series database and percentile math
│   └── ws_client.py          # RFC 6455 WebSocket client probe (zero dependencies)
├── tests/
│   ├── test_alerts.py        # Webhook alert dispatch tests
│   ├── test_assertions.py    # Assertion engine unit tests
│   ├── test_cli.py           # CLI subcommands and option tests
│   ├── test_config.py        # Configuration validation and file loading tests
│   ├── test_e2e.py           # End-to-end integration tests with mock daemon
│   ├── test_reporter.py      # Terminal, JSON, and HTML report tests
│   ├── test_storage.py       # SQLite persistence and percentile aggregation tests
│   └── test_ws.py            # RFC 6455 WebSocket framing, handshake & probe tests
├── sentinel.example.json     # Ready-to-use starter configuration template
├── pyproject.toml            # Modern PEP 518/621 packaging metadata
└── README.md                 # System documentation and usage guide
```

---

## 🚀 Installation

### Using pip / pipx (Editable or Standard)

Clone or navigate to the project directory:

```bash
git clone https://github.com/Abrar892/api-sentinel.git
cd api-sentinel
pip install -e .
```

Verify the installation:

```bash
api-sentinel --help
```

---

## 📖 Quick Start & Usage

### 1. Initialize Configuration

Generate a clean `sentinel.json` configuration file:

```bash
api-sentinel init --output sentinel.json
```

Or configure custom targets:

```json
{
  "name": "Production Microservices Sentinel",
  "environment": "production",
  "db_path": ".sentinel/sentinel.db",
  "concurrency": 4,
  "targets": [
    {
      "id": "users-api",
      "name": "Users Service",
      "url": "https://api.example.com/v1/users",
      "method": "GET",
      "timeout_seconds": 5.0,
      "max_retries": 2,
      "sla_latency_threshold_ms": 350.0,
      "assertions": [
        { "rule_type": "status_code", "expected": 200, "operator": "eq" },
        { "rule_type": "max_latency_ms", "expected": 400.0, "operator": "lte" },
        { "rule_type": "header_match", "field_name": "content-type", "expected": "application/json", "operator": "contains" },
        { "rule_type": "json_path", "field_name": "users.0.role", "expected": "admin", "operator": "eq" }
      ]
    }
  ]
}
```

### 2. Run a Probe Check

Run an immediate check against all targets and view the formatted terminal summary:

```bash
api-sentinel check --config sentinel.json
```

### 3. Generate HTML & JSON Reports

Generate an interactive HTML dashboard:

```bash
api-sentinel check --config sentinel.json --format html --output report.html
```

Generate a machine-readable JSON output:

```bash
api-sentinel check --config sentinel.json --format json --output report.json
```

### 4. CI/CD Quality Gate

Use `--fail-on-unhealthy` to return exit code `2` if any endpoint is failing, allowing pipelines (GitHub Actions, GitLab CI) to stop bad deployments:

```bash
api-sentinel check --config sentinel.json --fail-on-unhealthy
```

### 5. Start the Embedded Mock Server

For offline development or testing without touching production services:

```bash
api-sentinel serve-mock --host 127.0.0.1 --port 8080
```

Available mock endpoints:
- `GET /health` &rarr; Returns 200 OK
- `GET /delay?ms=250` &rarr; Simulates slow latency
- `GET /fault?code=500` &rarr; Simulates upstream 500 error
- `GET /users` &rarr; Returns JSON user records

---

## 🧪 Testing

API Sentinel comes with an automated test suite covering unit tests, SQLite persistence, percentile mathematics, reporters, and end-to-end integration with the mock server.

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

Test Results:
```text
test_body_regex_and_contains (test_assertions.TestAssertions) ... ok
test_extract_json_path_nested (test_assertions.TestAssertions) ... ok
test_header_match (test_assertions.TestAssertions) ... ok
test_json_path_assertion (test_assertions.TestAssertions) ... ok
test_latency_assertion (test_assertions.TestAssertions) ... ok
test_status_code_assertion (test_assertions.TestAssertions) ... ok
test_cmd_init_and_check (test_cli.TestCli) ... ok
test_parser_init (test_cli.TestCli) ... ok
test_config_save_and_load (test_config.TestConfig) ... ok
test_invalid_operator (test_config.TestConfig) ... ok
test_invalid_rule_type (test_config.TestConfig) ... ok
test_monitor_config_duplicate_ids (test_config.TestConfig) ... ok
test_target_invalid_method (test_config.TestConfig) ... ok
test_target_invalid_url (test_config.TestConfig) ... ok
test_target_negative_timeout (test_config.TestConfig) ... ok
test_valid_assertion_rule (test_config.TestConfig) ... ok
test_valid_target_config (test_config.TestConfig) ... ok
test_full_pipeline_healthy_degraded_unhealthy (test_e2e.TestE2E) ... ok
test_html_reporter (test_reporter.TestReporter) ... ok
test_json_reporter (test_reporter.TestReporter) ... ok
test_terminal_reporter (test_reporter.TestReporter) ... ok
test_incident_lifecycle (test_storage.TestStorage) ... ok
test_percentile_calculation (test_storage.TestStorage) ... ok
test_save_and_retrieve_probe (test_storage.TestStorage) ... ok
test_target_metrics_aggregation (test_storage.TestStorage) ... ok
----------------------------------------------------------------------
Ran 25 tests in 1.050s

OK
```

---

## ⚠️ Known Limitations

- **Authentication Handshakes:** Currently supports bearer tokens, API keys, and basic authentication via custom request headers. Multi-step OAuth2 redirect workflows require external pre-authenticated token generation.
- **Binary Stream Decoding:** WebSocket payload assertions are optimized for UTF-8 text, JSON frames, and Ping/Pong health checks; custom Protobuf / MessagePack binary decoding requires custom client unpacking.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
