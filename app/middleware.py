import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.limiter import RedisRateLimiter
from app.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException, CircuitState
from app.config import settings
from app import metrics

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RedisRateLimiter, circuit_breaker: CircuitBreaker):
        super().__init__(app)
        self.limiter = limiter
        self.cb = circuit_breaker

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/health", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)

        # Update circuit breaker gauge metric
        state_map = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}
        metrics.CIRCUIT_BREAKER_STATE.set(state_map[self.cb.state])

        client_ip = request.client.host if request.client else "unknown"
        identifier = request.headers.get("X-API-Key", client_ip)

        start_time = time.perf_counter()
        try:
            # Measure Redis latency within the circuit breaker
            allowed, remaining, retry_after = await self.cb.call(
                self.limiter.check_rate_limit,
                identifier=identifier,
                limit=settings.RATE_LIMIT_REQUESTS,
                window=settings.RATE_LIMIT_WINDOW_SECONDS
            )
            metrics.RATE_LIMIT_REDIS_LATENCY_SECONDS.observe(time.perf_counter() - start_time)

            if not allowed:
                metrics.RATE_LIMIT_EVALUATIONS_TOTAL.labels(status="blocked").inc()
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests", "retry_after": retry_after},
                    headers={
                        "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Degraded": "false"
                    }
                )

            metrics.RATE_LIMIT_EVALUATIONS_TOTAL.labels(status="allowed").inc()
            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Degraded"] = "false"
            return response

        except (Exception, CircuitBreakerOpenException):
            # FAIL-OPEN POLICY: Allow traffic through when Redis fails or times out
            metrics.RATE_LIMIT_EVALUATIONS_TOTAL.labels(status="fail_open").inc()

            response: Response = await call_next(request)
            response.headers["X-RateLimit-Degraded"] = "true"
            return response