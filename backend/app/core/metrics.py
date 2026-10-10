"""Minimal in-process metrics with Prometheus text exposition.

Kept dependency-free on purpose: counters and latency histograms for HTTP
requests now; AI-specific series (tokens, cost, retrieval latency) are added
through the same `metrics` object in later phases. Swapping in
`prometheus_client` later only touches this module.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Up to 5 minutes: a CPU-only 3B model takes 20-90 s per answer and minutes per summary.
LATENCY_BUCKETS_MS = (
    5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, 300000,
)  # fmt: skip


@dataclass
class _Histogram:
    buckets: list[int] = field(default_factory=lambda: [0] * len(LATENCY_BUCKETS_MS))
    count: int = 0
    total: float = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for index, bound in enumerate(LATENCY_BUCKETS_MS):
            if value <= bound:
                self.buckets[index] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC).isoformat()
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = defaultdict(
            _Histogram
        )

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, tuple(sorted(labels.items())))] += amount

    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        with self._lock:
            self._histograms[(name, tuple(sorted(labels.items())))].observe(value_ms)

    def observe_request(self, method: str, path: str, status: int, duration_ms: float) -> None:
        labels = {"method": method, "path": path, "status": str(status)}
        self.inc("http_requests_total", **labels)
        self.observe("http_request_duration_ms", duration_ms, method=method, path=path)

    def snapshot(self) -> dict[str, object]:
        """JSON-friendly view for the in-app diagnostics page."""
        with self._lock:
            return {
                "counters": [
                    {"name": name, "labels": dict(labels), "value": value}
                    for (name, labels), value in self._counters.items()
                ],
                "histograms": [
                    {
                        "name": name,
                        "labels": dict(labels),
                        "count": hist.count,
                        "mean_ms": round(hist.total / hist.count, 2) if hist.count else 0.0,
                    }
                    for (name, labels), hist in self._histograms.items()
                ],
            }

    def histogram_summary(self, name: str) -> dict[str, object] | None:
        """All label sets of one histogram merged: count, mean, p50/p95 estimated from buckets.

        Estimates interpolate linearly inside the bucket (as Prometheus' histogram_quantile
        does), so they're as precise as the bucket bounds, not exact.
        """
        with self._lock:
            hists = [h for (n, _), h in self._histograms.items() if n == name and h.count]
            if not hists:
                return None
            buckets = [sum(h.buckets[i] for h in hists) for i in range(len(LATENCY_BUCKETS_MS))]
            count = sum(h.count for h in hists)
            total = sum(h.total for h in hists)
        return {
            "count": count,
            "mean_ms": round(total / count, 1),
            "p50_ms": _quantile(0.5, buckets, count),
            "p95_ms": _quantile(0.95, buckets, count),
        }

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{format_labels(labels)} {value}")
            for (name, labels), hist in sorted(self._histograms.items()):
                # observe() increments every bucket with value <= bound, so counts are
                # already cumulative as Prometheus expects.
                for bound, count in zip(LATENCY_BUCKETS_MS, hist.buckets, strict=True):
                    lines.append(
                        f"{name}_bucket{format_labels((*labels, ('le', str(bound))))} {count}"
                    )
                lines.append(
                    f"{name}_bucket{format_labels((*labels, ('le', '+Inf')))} {hist.count}"
                )
                lines.append(f"{name}_count{format_labels(labels)} {hist.count}")
                lines.append(f"{name}_sum{format_labels(labels)} {round(hist.total, 3)}")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


def _quantile(q: float, cumulative: list[int], count: int) -> float | None:
    rank = q * count
    lower_bound, lower_count = 0.0, 0
    for bound, seen in zip(LATENCY_BUCKETS_MS, cumulative, strict=True):
        if seen >= rank:
            inside = seen - lower_count
            fraction = (rank - lower_count) / inside if inside else 1.0
            return round(lower_bound + (bound - lower_bound) * fraction, 1)
        lower_bound, lower_count = float(bound), seen
    return float(LATENCY_BUCKETS_MS[-1])  # beyond the last bucket: report its bound


def format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    escaped = (f'{key}="{value.replace(chr(34), chr(92) + chr(34))}"' for key, value in labels)
    return "{" + ",".join(escaped) + "}"


metrics = MetricsRegistry()
