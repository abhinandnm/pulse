import math
from datetime import datetime, timezone
from typing import List, Dict, Optional
import numpy as np

from pulse.domain.types import Bank, PaymentMethod, ErrorCode, RouteStatus, PredictiveHealth
from pulse.domain.transaction import TransactionResult
from pulse.domain.route import RouteHealth
from pulse.domain.telemetry import ConfidenceInterval, LatencyMetrics, TelemetrySnapshot


def compute_wilson_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    """
    Calculate Wilson score confidence interval for binomial success rate.
    Handles small sample sizes robustly without exploding bounds.
    """
    if total <= 0:
        return ConfidenceInterval(lower=0.0, upper=1.0, confidence_level=confidence)

    # Standard normal quantile: 1.96 for 95%
    z = 1.95996 if abs(confidence - 0.95) < 0.01 else 2.576
    p_hat = successes / total

    denominator = 1.0 + (z ** 2) / total
    center = (p_hat + (z ** 2) / (2 * total)) / denominator
    margin = (z * math.sqrt((p_hat * (1.0 - p_hat) / total) + ((z ** 2) / (4 * (total ** 2))))) / denominator

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    return ConfidenceInterval(
        lower=round(lower, 4),
        upper=round(upper, 4),
        confidence_level=confidence,
    )


def compute_latency_metrics(latencies: List[float]) -> LatencyMetrics:
    """Calculate p50, p90, p95, p99, mean, min, max for a list of latency numbers."""
    if not latencies:
        return LatencyMetrics()

    arr = np.array(latencies)
    return LatencyMetrics(
        p50_ms=round(float(np.percentile(arr, 50)), 2),
        p90_ms=round(float(np.percentile(arr, 90)), 2),
        p95_ms=round(float(np.percentile(arr, 95)), 2),
        p99_ms=round(float(np.percentile(arr, 99)), 2),
        mean_ms=round(float(np.mean(arr)), 2),
        min_ms=round(float(np.min(arr)), 2),
        max_ms=round(float(np.max(arr)), 2),
    )


class MetricsCalculator:
    """Computes comprehensive operational metrics from a set of transaction results."""

    @staticmethod
    def compute_snapshot(
        results: List[TransactionResult],
        window_seconds: int = 60,
        quarantined_routes: Optional[Dict[str, datetime]] = None,
    ) -> TelemetrySnapshot:
        total = len(results)
        if total == 0:
            return TelemetrySnapshot(
                window_seconds=window_seconds,
                total_transactions=0,
                successful_transactions=0,
                failed_transactions=0,
                success_rate=1.0,
                error_rate=0.0,
                timeout_rate=0.0,
                latency=LatencyMetrics(),
                success_rate_ci=ConfidenceInterval(lower=1.0, upper=1.0),
                predictive_health=PredictiveHealth.HEALTHY,
            )

        successes = sum(1 for r in results if r.success)
        failures = total - successes
        timeouts = sum(1 for r in results if r.error_code == ErrorCode.PSP_TIMEOUT)

        sr = round(successes / total, 4)
        er = round(failures / total, 4)
        tr = round(timeouts / total, 4)

        latencies = [r.latency_ms for r in results]
        latency_metrics = compute_latency_metrics(latencies)
        ci = compute_wilson_interval(successes, total)

        # Error distribution
        error_dist: Dict[str, int] = {}
        for r in results:
            if not r.success:
                code_str = r.error_code.value
                error_dist[code_str] = error_dist.get(code_str, 0) + 1

        # Per-route breakdown
        route_buckets: Dict[str, List[TransactionResult]] = {}
        for r in results:
            route_id = r.transaction.route_id
            route_buckets.setdefault(route_id, []).append(r)

        route_health: Dict[str, RouteHealth] = {}
        q_routes = quarantined_routes or {}
        now = datetime.now(timezone.utc)

        for route_id, r_list in route_buckets.items():
            r_total = len(r_list)
            r_succ = sum(1 for item in r_list if item.success)
            r_fail = r_total - r_succ
            r_timeouts = sum(1 for item in r_list if item.error_code == ErrorCode.PSP_TIMEOUT)

            r_sr = round(r_succ / r_total, 4)
            r_er = round(r_fail / r_total, 4)
            r_tr = round(r_timeouts / r_total, 4)

            r_latencies = [item.latency_ms for item in r_list]
            r_p95 = round(float(np.percentile(r_latencies, 95)), 2) if r_latencies else 0.0

            is_quar = route_id in q_routes and q_routes[route_id] > now
            status = RouteStatus.QUARANTINED if is_quar else (
                RouteStatus.DEGRADED if r_sr < 0.85 or r_p95 > 2000.0 else RouteStatus.ACTIVE
            )

            route_health[route_id] = RouteHealth(
                route_id=route_id,
                status=status,
                success_rate=r_sr,
                error_rate=r_er,
                timeout_rate=r_tr,
                p95_latency_ms=r_p95,
                total_transactions=r_total,
                failed_transactions=r_fail,
                is_quarantined=is_quar,
                quarantined_until=q_routes.get(route_id),
                last_updated=now,
            )

        # Per-bank success rates
        bank_buckets: Dict[str, List[TransactionResult]] = {}
        for r in results:
            bank_buckets.setdefault(r.transaction.bank.value, []).append(r)

        bank_breakdown: Dict[str, float] = {}
        for b_name, b_list in bank_buckets.items():
            b_succ = sum(1 for item in b_list if item.success)
            bank_breakdown[b_name] = round(b_succ / len(b_list), 4)

        # Predictive health classification
        if sr < 0.70 or tr > 0.15 or latency_metrics.p95_ms > 3000.0:
            pred_health = PredictiveHealth.CRITICAL
        elif sr < 0.90 or tr > 0.05 or latency_metrics.p95_ms > 1500.0:
            pred_health = PredictiveHealth.DEGRADED
        else:
            pred_health = PredictiveHealth.HEALTHY

        return TelemetrySnapshot(
            window_seconds=window_seconds,
            total_transactions=total,
            successful_transactions=successes,
            failed_transactions=failures,
            success_rate=sr,
            error_rate=er,
            timeout_rate=tr,
            latency=latency_metrics,
            success_rate_ci=ci,
            route_health=route_health,
            error_distribution=error_dist,
            bank_breakdown=bank_breakdown,
            predictive_health=pred_health,
        )
