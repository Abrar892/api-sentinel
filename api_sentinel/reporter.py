"""Multi-format reporting suite: Terminal tables, JSON export, and standalone HTML dashboard."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import HealthStatus, IncidentRecord, ProbeResult, TargetMetrics


class TerminalReporter:
    """Renders formatted tables and health indicators to the console."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "gray": "\033[90m",
        "white": "\033[97m",
    }

    @classmethod
    def _use_color(cls) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        return sys.stdout.isatty() or os.name == "nt"

    @classmethod
    def c(cls, text: str, color_key: str) -> str:
        if not cls._use_color():
            return text
        code = cls.COLORS.get(color_key, "")
        reset = cls.COLORS.get("reset", "")
        return f"{code}{text}{reset}"

    @classmethod
    def format_status(cls, status: HealthStatus) -> str:
        if status == HealthStatus.HEALTHY:
            return cls.c("  PASS  ", "green")
        if status == HealthStatus.DEGRADED:
            return cls.c("  WARN  ", "yellow")
        if status == HealthStatus.UNHEALTHY:
            return cls.c("  FAIL  ", "red")
        return cls.c("  UNKN  ", "gray")

    @classmethod
    def render_probe_summary(
        cls, results: List[ProbeResult], metrics: Optional[List[TargetMetrics]] = None
    ) -> str:
        lines: List[str] = []
        lines.append("")
        lines.append(cls.c("=" * 84, "cyan"))
        lines.append(
            cls.c("  API SENTINEL - SYNTHETIC HEALTH PROBE REPORT", "bold")
            + f"  [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}]"
        )
        lines.append(cls.c("=" * 84, "cyan"))

        header = f"{'STATUS':<10} {'TARGET':<24} {'METHOD':<7} {'CODE':<6} {'LATENCY':<10} {'DETAILS'}"
        lines.append(cls.c(header, "bold"))
        lines.append(cls.c("-" * 84, "gray"))

        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0
        total_latency = 0.0

        for r in results:
            status_badge = cls.format_status(r.status)
            target_name = (r.target_name[:22] + "..") if len(r.target_name) > 24 else r.target_name
            method = r.method
            code = str(r.status_code) if r.status_code is not None else "ERR"
            latency = f"{r.latency_ms:.1f}ms"
            total_latency += r.latency_ms

            if r.status == HealthStatus.HEALTHY:
                healthy_count += 1
                details = cls.c(f"{len(r.assertions)} assertions passed", "gray")
            elif r.status == HealthStatus.DEGRADED:
                degraded_count += 1
                details = cls.c(r.error or "Degraded performance", "yellow")
            else:
                unhealthy_count += 1
                details = cls.c(r.error or "Check failed", "red")

            lines.append(f"[{status_badge}] {target_name:<24} {method:<7} {code:<6} {latency:<10} {details}")

            # Print failing assertions if any
            if r.status != HealthStatus.HEALTHY:
                for a in r.assertions:
                    if not a.passed:
                        lines.append(f"         {cls.c('x', 'red')} {a.rule_type} on '{a.field_name}': {a.message}")

        lines.append(cls.c("-" * 84, "gray"))

        # Summary statistics
        total = len(results)
        avg_lat = total_latency / total if total > 0 else 0.0
        summary_str = (
            f"  Total: {total} | "
            + cls.c(f"Healthy: {healthy_count}", "green")
            + " | "
            + cls.c(f"Degraded: {degraded_count}", "yellow")
            + " | "
            + cls.c(f"Unhealthy: {unhealthy_count}", "red")
            + f" | Avg Latency: {avg_lat:.1f}ms"
        )
        lines.append(summary_str)
        lines.append(cls.c("=" * 84, "cyan"))
        lines.append("")

        return "\n".join(lines)


class JsonReporter:
    """Serializes probe results and historical aggregates to machine-readable JSON."""

    @staticmethod
    def render(
        results: List[ProbeResult],
        metrics: Optional[List[TargetMetrics]] = None,
        incidents: Optional[List[IncidentRecord]] = None,
    ) -> str:
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_targets": len(results),
                "healthy": sum(1 for r in results if r.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for r in results if r.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for r in results if r.status == HealthStatus.UNHEALTHY),
                "avg_latency_ms": round(
                    sum(r.latency_ms for r in results) / len(results), 2
                ) if results else 0.0,
            },
            "probes": [r.to_dict() for r in results],
            "metrics": [m.to_dict() for m in metrics] if metrics else [],
            "open_incidents": [inc.to_dict() for inc in incidents] if incidents else [],
        }
        return json.dumps(data, indent=2)


class HtmlReporter:
    """Generates a standalone, dependency-free responsive HTML5 dashboard."""

    @classmethod
    def render(
        cls,
        title: str,
        results: List[ProbeResult],
        metrics: Optional[List[TargetMetrics]] = None,
        incidents: Optional[List[IncidentRecord]] = None,
    ) -> str:
        total = len(results)
        healthy = sum(1 for r in results if r.status == HealthStatus.HEALTHY)
        degraded = sum(1 for r in results if r.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for r in results if r.status == HealthStatus.UNHEALTHY)
        avg_latency = round(sum(r.latency_ms for r in results) / total, 2) if total else 0.0

        # Construct latency SVG bars
        max_bar_latency = max((r.latency_ms for r in results), default=100.0)
        if max_bar_latency <= 0:
            max_bar_latency = 1.0

        svg_bars = []
        for i, r in enumerate(results):
            height = max(8, int((r.latency_ms / max_bar_latency) * 100))
            y = 120 - height
            color = "#10b981" if r.status == HealthStatus.HEALTHY else ("#f59e0b" if r.status == HealthStatus.DEGRADED else "#ef4444")
            x = 20 + (i * 65)
            svg_bars.append(
                f'<rect x="{x}" y="{y}" width="42" height="{height}" rx="4" fill="{color}" />'
                f'<text x="{x + 21}" y="135" font-size="11" fill="#94a3b8" text-anchor="middle">{r.target_name[:5]}</text>'
                f'<text x="{x + 21}" y="{y - 5}" font-size="10" fill="#e2e8f0" text-anchor="middle">{int(r.latency_ms)}ms</text>'
            )
        svg_content = "".join(svg_bars)
        svg_width = max(600, len(results) * 70 + 40)

        # Table rows
        table_rows = []
        for r in results:
            badge_class = f"badge-{r.status.value}"
            code_text = str(r.status_code) if r.status_code else "ERROR"
            row_html = f"""
            <tr>
              <td><span class="badge {badge_class}">{r.status.value.upper()}</span></td>
              <td><strong>{r.target_name}</strong><br><small class="text-muted">{r.url}</small></td>
              <td><code>{r.method}</code></td>
              <td><code>{code_text}</code></td>
              <td><strong>{r.latency_ms:.1f} ms</strong></td>
              <td>{r.error or '<span class="text-success">All assertions satisfied</span>'}</td>
            </tr>
            """
            table_rows.append(row_html)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} - API Sentinel Dashboard</title>
  <style>
    :root {{
      --bg-color: #0f172a;
      --card-bg: #1e293b;
      --border-color: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --green: #10b981;
      --yellow: #f59e0b;
      --red: #ef4444;
      --blue: #38bdf8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-color);
      color: var(--text-main);
      padding: 2rem;
      line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border-color);
    }}
    h1 {{ font-size: 1.75rem; font-weight: 700; color: var(--blue); }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 1.25rem;
    }}
    .stat-val {{ font-size: 2rem; font-weight: 700; margin-top: 0.5rem; }}
    .chart-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 2rem;
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card-bg);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border-color);
    }}
    th, td {{
      padding: 0.85rem 1rem;
      text-align: left;
      border-bottom: 1px solid var(--border-color);
      font-size: 0.9rem;
    }}
    th {{ background: #162033; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }}
    .badge {{
      display: inline-block;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
    }}
    .badge-healthy {{ background: rgba(16, 185, 129, 0.2); color: var(--green); border: 1px solid var(--green); }}
    .badge-degraded {{ background: rgba(245, 158, 11, 0.2); color: var(--yellow); border: 1px solid var(--yellow); }}
    .badge-unhealthy {{ background: rgba(239, 68, 68, 0.2); color: var(--red); border: 1px solid var(--red); }}
    .text-success {{ color: var(--green); }}
    .text-muted {{ color: var(--text-muted); }}
    code {{ background: #0f172a; padding: 0.15rem 0.35rem; border-radius: 4px; font-size: 0.85rem; font-family: monospace; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>API Sentinel</h1>
        <p class="text-muted">{title} &bull; Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
      </div>
    </header>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="text-muted">Total Targets</div>
        <div class="stat-val">{total}</div>
      </div>
      <div class="stat-card">
        <div class="text-muted">Healthy</div>
        <div class="stat-val" style="color: var(--green);">{healthy}</div>
      </div>
      <div class="stat-card">
        <div class="text-muted">Degraded</div>
        <div class="stat-val" style="color: var(--yellow);">{degraded}</div>
      </div>
      <div class="stat-card">
        <div class="text-muted">Unhealthy</div>
        <div class="stat-val" style="color: var(--red);">{unhealthy}</div>
      </div>
      <div class="stat-card">
        <div class="text-muted">Avg Latency</div>
        <div class="stat-val" style="color: var(--blue);">{avg_latency} ms</div>
      </div>
    </div>

    <div class="chart-card">
      <h3 style="margin-bottom: 1rem; font-size: 1rem;">Endpoint Latency Distribution</h3>
      <svg width="{svg_width}" height="150" viewBox="0 0 {svg_width} 150">
        <line x1="10" y1="120" x2="{svg_width - 10}" y2="120" stroke="#334155" stroke-width="1"/>
        {svg_content}
      </svg>
    </div>

    <h3 style="margin-bottom: 1rem; font-size: 1.1rem;">Endpoint Probes & Audit Results</h3>
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Target</th>
          <th>Method</th>
          <th>HTTP Code</th>
          <th>Latency</th>
          <th>Assertion Outcome</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
        return html
