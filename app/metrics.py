from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# 1. Total rate-limit evaluations segmented by verdict
RATE_LIMIT_EVALUATIONS_TOTAL = Counter(
    "rate_limiter_evaluations_total",
    "Total rate limit checks partitioned by outcome",
    ["status"]  # "allowed", "blocked", "fail_open"
)

# 2. Redis operation latency distribution
RATE_LIMIT_REDIS_LATENCY_SECONDS = Histogram(
    "rate_limiter_redis_latency_seconds",
    "Latency of Redis rate-limiting calls in seconds",
    buckets=[0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1]
)

# 3. Current Circuit Breaker State (0=CLOSED, 1=HALF_OPEN, 2=OPEN)
CIRCUIT_BREAKER_STATE = Gauge(
    "rate_limiter_circuit_breaker_state",
    "Current state of the Redis circuit breaker"
)

def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)