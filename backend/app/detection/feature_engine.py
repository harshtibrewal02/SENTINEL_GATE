import time
import json
import logging
import numpy as np
from typing import Dict, List, Any
from app.rate_limiter.redis_limiter import redis_client

logger = logging.getLogger("feature_engine")

class FeatureEngine:
    async def record_request(self, client_id: str, path: str, method: str, status_code: int) -> None:
        """
        Record a request log entry in Redis list for rolling features.
        """
        key = f"client_reqs:{client_id}"
        entry = {
            "t": time.time(),
            "s": status_code,
            "m": method,
            "p": path
        }
        try:
            # Add to list and keep last 200 entries (plenty for 60s statistics)
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.lpush(key, json.dumps(entry))
                pipe.ltrim(key, 0, 199)
                pipe.expire(key, 3600)  # Expire in 1 hour if inactive
                await pipe.execute()
        except Exception as e:
            logger.error(f"Error recording request features: {e}")

    async def get_client_features(self, client_id: str) -> Dict[str, Any]:
        """
        Calculate rolling statistics and behavioral features for a client over the last 60 seconds.
        """
        key = f"client_reqs:{client_id}"
        now = time.time()
        
        try:
            raw_entries = await redis_client.lrange(key, 0, -1)
        except Exception as e:
            logger.error(f"Error fetching request features from Redis: {e}")
            raw_entries = []

        entries = []
        for raw in raw_entries:
            try:
                item = json.loads(raw)
                # Keep only requests within the last 60 seconds
                if now - item["t"] <= 60.0:
                    entries.append(item)
            except Exception:
                continue

        # Sort entries ascending by time
        entries.sort(key=lambda x: x["t"])

        total_reqs = len(entries)
        if total_reqs == 0:
            return {
                "rpm": 0,
                "rps": 0.0,
                "burstiness": 0.0,
                "error_rate": 0.0,
                "unique_endpoints": 0,
                "max_endpoint_repeat_ratio": 0.0,
                "traffic_spike_ratio": 1.0,
                "last_activity": now
            }

        # 1. RPM (Requests Per Minute)
        rpm = total_reqs

        # 2. RPS (Requests Per Second in last 2 seconds)
        reqs_last_2s = [e for e in entries if now - e["t"] <= 2.0]
        rps = len(reqs_last_2s) / 2.0

        # 3. Burstiness (Variance of request time intervals)
        burstiness = 0.0
        if total_reqs >= 3:
            intervals = []
            for i in range(1, len(entries)):
                intervals.append(entries[i]["t"] - entries[i - 1]["t"])
            if len(intervals) > 1:
                # Higher variance indicates bursty behavior
                burstiness = float(np.var(intervals))

        # 4. Error Rate (4xx/5xx status codes)
        errors = [e for e in entries if e["s"] >= 400]
        error_rate = len(errors) / total_reqs if total_reqs > 0 else 0.0

        # 5. Unique Endpoints
        endpoints = [e["p"] for e in entries]
        unique_endpoints = len(set(endpoints))

        # 6. Max Endpoint Repeat Ratio
        max_endpoint_repeat_ratio = 0.0
        if total_reqs > 0:
            path_counts = {}
            for p in endpoints:
                path_counts[p] = path_counts.get(p, 0) + 1
            max_repeat = max(path_counts.values()) if path_counts else 0
            max_endpoint_repeat_ratio = max_repeat / total_reqs

        # 7. Traffic Spike Ratio (last 5s RPS vs last 60s RPS)
        reqs_last_5s = [e for e in entries if now - e["t"] <= 5.0]
        rps_5s = len(reqs_last_5s) / 5.0
        rps_60s = total_reqs / 60.0
        
        # Avoid division by zero
        if rps_60s > 0.05:
            traffic_spike_ratio = rps_5s / rps_60s
        else:
            traffic_spike_ratio = 1.0

        return {
            "rpm": rpm,
            "rps": rps,
            "burstiness": burstiness,
            "error_rate": error_rate,
            "unique_endpoints": unique_endpoints,
            "max_endpoint_repeat_ratio": max_endpoint_repeat_ratio,
            "traffic_spike_ratio": traffic_spike_ratio,
            "last_activity": entries[-1]["t"]
        }

    async def get_active_clients(self) -> List[str]:
        """
        Identify active client IDs using keys from Redis rate limiter or client request list.
        """
        try:
            # Scan keys starting with client_reqs:
            keys = []
            cursor = 0
            while True:
                cursor, scan_keys = await redis_client.scan(cursor, match="client_reqs:*", count=100)
                keys.extend(scan_keys)
                if cursor == 0:
                    break
            return [k.split("client_reqs:")[1] for k in keys]
        except Exception as e:
            logger.error(f"Error scanning active clients: {e}")
            return []

feature_engine = FeatureEngine()
