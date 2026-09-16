import time
from typing import Tuple
import redis.asyncio as aioredis
from app.config import settings

# KEYS[1]: Current window bucket key (e.g., rl:{id}:{window_epoch})
# KEYS[2]: Previous window bucket key (e.g., rl:{id}:{window_epoch - 1})
# ARGV[1]: Window size in seconds
# ARGV[2]: Max capacity limit
# ARGV[3]: Current timestamp (float)
# Returns: {allowed (1/0), remaining, retry_after}
SLIDING_WINDOW_COUNTER_LUA = """
local current_key = KEYS[1]
local prev_key = KEYS[2]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Current bucket offset within the window
local current_bucket_start = math.floor(now / window) * window
local elapsed = now - current_bucket_start
local weight = (window - elapsed) / window

-- Fetch counts from both buckets
local prev_count = tonumber(redis.call('GET', prev_key) or "0")
local curr_count = tonumber(redis.call('GET', current_key) or "0")

local estimated_count = math.floor(prev_count * weight + curr_count)

if estimated_count < limit then
    -- Increment current bucket and refresh TTL (2x window for safe overlap)
    redis.call('INCR', current_key)
    redis.call('EXPIRE', current_key, math.ceil(window * 2))
    return {1, limit - estimated_count - 1, 0}
else
    -- Compute seconds until current window boundary passes
    local retry_after = math.max(1, math.ceil(window - elapsed))
    return {0, 0, retry_after}
end
"""

class RedisRateLimiter:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self._script = self.redis.register_script(SLIDING_WINDOW_COUNTER_LUA)

    async def check_rate_limit(
        self,
        identifier: str,
        limit: int = settings.RATE_LIMIT_REQUESTS,
        window: int = settings.RATE_LIMIT_WINDOW_SECONDS,
    ) -> Tuple[bool, int, int]:
        now = time.time()
        bucket_epoch = int(now // window)

        curr_key = f"rl:{identifier}:{bucket_epoch}"
        prev_key = f"rl:{identifier}:{bucket_epoch - 1}"

        result = await self._script(
            keys=[curr_key, prev_key],
            args=[str(window), str(limit), str(now)]
        )

        return bool(result[0]), int(result[1]), int(result[2])