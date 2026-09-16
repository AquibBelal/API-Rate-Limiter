from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from fastapi import FastAPI
from app.config import settings
from app.limiter import RedisRateLimiter
from app.circuit_breaker import CircuitBreaker
from app.middleware import RateLimitMiddleware
from app.metrics import metrics_endpoint

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_pool = aioredis.ConnectionPool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True
    )
    redis_client = aioredis.Redis(connection_pool=redis_pool)
    limiter = RedisRateLimiter(redis_client)
    circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0, call_timeout=0.02)

    app.state.redis = redis_client
    app.state.limiter = limiter
    app.state.circuit_breaker = circuit_breaker

    yield

    await redis_client.aclose()
    await redis_pool.disconnect()

app = FastAPI(title="Distributed Rate Limiter Service", lifespan=lifespan)

@app.middleware("http")
async def apply_rate_limiting(request, call_next):
    limiter = request.app.state.limiter
    circuit_breaker = request.app.state.circuit_breaker
    middleware = RateLimitMiddleware(app=request.app, limiter=limiter, circuit_breaker=circuit_breaker)
    return await middleware.dispatch(request, call_next)


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/metrics")
async def get_metrics():
    return metrics_endpoint()

@app.get("/api/v1/resource")
async def get_resource():
    return {"status": "success", "data": "Protected payload"}