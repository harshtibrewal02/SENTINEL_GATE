import time
import logging
import asyncio
import fnmatch
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger("redis_limiter")

# --- In-Memory Redis Implementation for Local Fallback ---
class InMemoryRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def _is_expired(self, key) -> bool:
        if key in self.ttls and self.ttls[key] < time.time():
            if key in self.data:
                del self.data[key]
            del self.ttls[key]
            return True
        return False

    async def ping(self):
        return True

    async def lpush(self, key, val):
        self._is_expired(key)
        if key not in self.data:
            self.data[key] = []
        if not isinstance(self.data[key], list):
            self.data[key] = []
        self.data[key].insert(0, val)
        return len(self.data[key])

    async def ltrim(self, key, start, stop):
        self._is_expired(key)
        if key in self.data and isinstance(self.data[key], list):
            self.data[key] = self.data[key][start:stop+1]
        return True

    async def lrange(self, key, start, stop):
        self._is_expired(key)
        if key not in self.data:
            return []
        if not isinstance(self.data[key], list):
            return []
        if stop == -1:
            return self.data[key][start:]
        return self.data[key][start:stop+1]

    async def expire(self, key, seconds):
        self.ttls[key] = time.time() + seconds
        return True

    async def hmget(self, key, *fields):
        self._is_expired(key)
        if key not in self.data:
            return [None] * len(fields)
        val = self.data[key]
        if not isinstance(val, dict):
            return [None] * len(fields)
        return [val.get(f) for f in fields]

    async def hmset(self, key, mapping):
        self._is_expired(key)
        if key not in self.data or not isinstance(self.data[key], dict):
            self.data[key] = {}
        for k, v in mapping.items():
            self.data[key][k] = v
        return True

    async def hget(self, key, field):
        self._is_expired(key)
        if key not in self.data:
            return None
        val = self.data[key]
        if not isinstance(val, dict):
            return None
        return val.get(field)

    async def scan(self, cursor, match, count):
        matched_keys = []
        pattern = match if match else "*"
        for k in self.data.keys():
            if not self._is_expired(k):
                if fnmatch.fnmatch(k, pattern):
                    matched_keys.append(k)
        return 0, matched_keys

    def pipeline(self, transaction=True):
        class Pipeline:
            def __init__(self, parent):
                self.parent = parent
                self.commands = []
            
            async def __aenter__(self):
                return self
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            
            def lpush(self, key, val):
                self.commands.append(("lpush", (key, val)))
                return self
            
            def ltrim(self, key, start, stop):
                self.commands.append(("ltrim", (key, start, stop)))
                return self
            
            def expire(self, key, seconds):
                self.commands.append(("expire", (key, seconds)))
                return self
            
            async def execute(self):
                for cmd, args in self.commands:
                    if cmd == "lpush":
                        await self.parent.lpush(*args)
                    elif cmd == "ltrim":
                        await self.parent.ltrim(*args)
                    elif cmd == "expire":
                        await self.parent.expire(*args)
                return True
        return Pipeline(self)

    def register_script(self, script_body):
        # We simulate the token bucket Lua script in python!
        async def run_script(keys, args):
            key = keys[0]
            capacity = float(args[0])
            refill_rate = float(args[1])
            requested = float(args[2])
            now = float(args[3])

            self._is_expired(key)
            if key not in self.data or not isinstance(self.data[key], dict):
                self.data[key] = {}
            
            bucket = self.data[key]
            tokens = bucket.get("tokens")
            last_refill = bucket.get("last_refill")

            if tokens is None:
                tokens = capacity
                last_refill = now
            else:
                tokens = float(tokens)
                last_refill = float(last_refill)
                elapsed = max(0.0, now - last_refill)
                refill = elapsed * refill_rate
                tokens = min(capacity, tokens + refill)

            if tokens >= requested:
                tokens = tokens - requested
                bucket["tokens"] = tokens
                bucket["last_refill"] = now
                self.ttls[key] = time.time() + 3600
                return [1, tokens]
            else:
                bucket["tokens"] = tokens
                bucket["last_refill"] = now
                self.ttls[key] = time.time() + 3600
                return [0, tokens]
        
        return run_script


import os

# --- Resilient Wrapper Class ---
class ResilientRedisClient:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", settings.REDIS_URL)
        self.real_client = redis.from_url(redis_url, decode_responses=True)
        self.mock_client = InMemoryRedis()
        self.active_client = self.real_client
        self.use_mock = False

    async def check_connection(self):
        try:
            await asyncio.wait_for(self.real_client.ping(), timeout=1.0)
            self.active_client = self.real_client
            self.use_mock = False
            logger.info("Successfully connected to Redis instance.")
        except Exception as e:
            logger.warning(f"Unable to connect to Redis ({e}). Falling back to InMemoryRedis.")
            self.active_client = self.mock_client
            self.use_mock = True

    async def ping(self):
        return await self.active_client.ping()

    async def lpush(self, key, val):
        return await self.active_client.lpush(key, val)

    async def ltrim(self, key, start, stop):
        return await self.active_client.ltrim(key, start, stop)

    async def lrange(self, key, start, stop):
        return await self.active_client.lrange(key, start, stop)

    async def expire(self, key, seconds):
        return await self.active_client.expire(key, seconds)

    async def hmget(self, key, *fields):
        return await self.active_client.hmget(key, *fields)

    async def hmset(self, key, mapping):
        return await self.active_client.hmset(key, mapping)

    async def hget(self, key, field):
        return await self.active_client.hget(key, field)

    async def scan(self, cursor, match, count):
        return await self.active_client.scan(cursor, match, count)

    def pipeline(self, transaction=True):
        return self.active_client.pipeline(transaction)

    def register_script(self, script_body):
        if self.use_mock:
            return self.mock_client.register_script(script_body)
        
        # Real Redis registration
        return self.real_client.register_script(script_body)


# Export single resilient instance
redis_client = ResilientRedisClient()

# Lua script to atomicaly evaluate and consume token bucket
LUA_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2]) -- tokens per second
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local limit_info = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(limit_info[1])
local last_refill = tonumber(limit_info[2])

if not tokens then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    local refill = elapsed * refill_rate
    tokens = math.min(capacity, tokens + refill)
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call("HMSET", key, "tokens", tokens, "last_refill", now)
    redis.call("EXPIRE", key, 3600)
    return {1, tokens}
else
    redis.call("HMSET", key, "tokens", tokens, "last_refill", now)
    redis.call("EXPIRE", key, 3600)
    return {0, tokens}
end
"""

class RedisTokenBucket:
    def __init__(self):
        self.script = None

    async def initialize(self):
        await redis_client.check_connection()
        try:
            self.script = redis_client.register_script(LUA_TOKEN_BUCKET)
            logger.info("Token Bucket initialization complete.")
        except Exception as e:
            logger.error(f"Failed to initialize rate limiter script: {e}")

    async def is_allowed(self, client_id: str, capacity: int, refill_rate_per_sec: float, cost: int = 1) -> tuple[bool, float]:
        if not self.script:
            await self.initialize()

        key = f"rate_limit:{client_id}"
        now = time.time()
        
        try:
            result = await self.script(keys=[key], args=[capacity, refill_rate_per_sec, cost, now])
            allowed, remaining = result
            return bool(allowed), float(remaining)
        except Exception as e:
            logger.error(f"Rate Limiter script execution failed: {e}")
            # Fallback fail-open
            return True, float(capacity)

rate_limiter = RedisTokenBucket()
