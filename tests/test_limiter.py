import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import redis.asyncio as aioredis
from app.main import app

@pytest_asyncio.fixture
async def client():
    # Setup test Redis client
    test_redis = aioredis.Redis(host="localhost", port=6379, db=1, decode_responses=True)
    await test_redis.flushdb()
    
    from app.limiter import RedisRateLimiter
    app.state.limiter = RedisRateLimiter(test_redis)
    app.state.redis = test_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await test_redis.flushdb()
    await test_redis.aclose()

@pytest.mark.asyncio
async def test_under_limit(client: AsyncClient):
    response = await client.get("/api/v1/resource")
    assert response.status_code == 200
    assert int(response.headers["X-RateLimit-Remaining"]) == 9

@pytest.mark.asyncio
async def test_exceed_limit(client: AsyncClient):
    # Burst 10 requests (settings default limit = 10)
    for _ in range(10):
        res = await client.get("/api/v1/resource")
        assert res.status_code == 200

    # 11th request triggers 429
    res = await client.get("/api/v1/resource")
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert res.json()["detail"] == "Too Many Requests"

@pytest.mark.asyncio
async def test_health_check_exempt(client: AsyncClient):
    for _ in range(15):
        res = await client.get("/health")
        assert res.status_code == 200