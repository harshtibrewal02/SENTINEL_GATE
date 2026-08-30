import time
import logging
from typing import Dict, List, Tuple, Any
from app.config import settings
from app.rate_limiter.redis_limiter import redis_client
from app.detection.anomaly_detector import anomaly_detector

logger = logging.getLogger("risk_engine")

class RiskEngine:
    def __init__(self):
        # Decay rate: risk points subtracted per second of inactivity
        self.decay_rate = 2.0  
        # Blending factor for smoothing risk transitions
        self.alpha = 0.6  

    async def get_and_update_risk(self, client_id: str, features: Dict[str, Any]) -> Tuple[int, List[str]]:
        """
        Retrieves the client's historical risk from Redis, decays it based on elapsed time,
        calculates the new instant risk from features & ML, blends them, and saves to Redis.
        
        Returns:
            (blended_risk_score: int, reasons: list[str])
        """
        now = time.time()
        key = f"client_risk:{client_id}"
        
        # 1. Fetch previous risk
        prev_score = 0.0
        prev_time = now
        try:
            stored = await redis_client.hmget(key, "score", "last_updated")
            if stored and stored[0] is not None:
                prev_score = float(stored[0])
                prev_time = float(stored[1])
        except Exception as e:
            logger.error(f"Error fetching risk state from Redis: {e}")

        # 2. Apply decay based on elapsed time
        elapsed = max(0.0, now - prev_time)
        decayed_prev = max(0.0, prev_score - (elapsed * self.decay_rate))

        # 3. Calculate instant risk and collect triggers
        instant_risk = 0.0
        reasons = []
        
        # Heuristics rules
        rpm = features.get("rpm", 0)
        rps = features.get("rps", 0.0)
        burstiness = features.get("burstiness", 0.0)
        error_rate = features.get("error_rate", 0.0)
        max_endpoint_repeat_ratio = features.get("max_endpoint_repeat_ratio", 0.0)
        traffic_spike_ratio = features.get("traffic_spike_ratio", 1.0)

        # Rate checks
        if rpm > 40:
            rpm_risk = min(35.0, (rpm - 40) * 0.5)
            instant_risk += rpm_risk
            if rpm > 60:
                reasons.append(f"Abnormally high request rate ({rpm} req/min)")
        
        # Burstiness check
        if burstiness > 0.05:
            burst_risk = min(25.0, burstiness * 150)
            instant_risk += burst_risk
            if burstiness > 0.15:
                reasons.append("High burstiness / irregular traffic spacing")

        # Error rate check
        if error_rate > 0.2:
            error_risk = min(35.0, error_rate * 40)
            instant_risk += error_risk
            reasons.append(f"High HTTP error rate ({error_rate:.0%})")

        # Endpoint repetition check
        if max_endpoint_repeat_ratio > 0.6 and rpm > 10:
            repeat_risk = min(25.0, (max_endpoint_repeat_ratio - 0.6) * 60)
            instant_risk += repeat_risk
            if max_endpoint_repeat_ratio > 0.8:
                reasons.append(f"Repeated endpoint requests ({max_endpoint_repeat_ratio:.0%})")

        # Traffic spike check
        if traffic_spike_ratio > 3.0:
            spike_risk = min(25.0, (traffic_spike_ratio - 3.0) * 4)
            instant_risk += spike_risk
            reasons.append(f"Sudden traffic spike ({traffic_spike_ratio:.1f}x baseline)")

        # ML Anomaly Score check
        ml_score = anomaly_detector.get_anomaly_score(features)
        if ml_score > 30.0:
            instant_risk += ml_score * 0.35
            if ml_score > 60.0:
                reasons.append(f"Anomalous traffic pattern (ML Score: {ml_score:.0f})")

        # Limit instant risk score to 100
        instant_risk = min(100.0, instant_risk)

        # 4. Blend previous decayed risk and instant risk
        # If the client is currently silent (no requests), we want to decay rapidly
        # If there's active requests, we smooth the climbing / falling
        if rpm == 0:
            blended_risk = decayed_prev
        else:
            blended_risk = (self.alpha * decayed_prev) + ((1.0 - self.alpha) * instant_risk)

        # Keep within bounds
        blended_risk = min(100.0, max(0.0, blended_risk))
        final_risk = int(round(blended_risk))

        # 5. Persist back to Redis
        try:
            await redis_client.hmset(key, {
                "score": blended_risk,
                "last_updated": now
            })
            await redis_client.expire(key, 3600)
        except Exception as e:
            logger.error(f"Error saving risk state to Redis: {e}")

        # If no reasons were logged but risk is elevated, add a generic message
        if final_risk > 15 and not reasons:
            reasons.append("Elevated background traffic indicators")

        return final_risk, reasons

    async def decay_client_risk_background(self, client_id: str) -> int:
        """
        Allows background worker or GET requests to decay the risk score 
        even if the client isn't making active requests (crucial for unblocking clients).
        """
        now = time.time()
        key = f"client_risk:{client_id}"
        try:
            stored = await redis_client.hmget(key, "score", "last_updated")
            if not stored or stored[0] is None:
                return 0
            
            prev_score = float(stored[0])
            prev_time = float(stored[1])
            
            elapsed = max(0.0, now - prev_time)
            decayed = max(0.0, prev_score - (elapsed * self.decay_rate))
            
            await redis_client.hmset(key, {
                "score": decayed,
                "last_updated": now
            })
            return int(round(decayed))
        except Exception as e:
            logger.error(f"Error decaying client risk background: {e}")
            return 0

risk_engine = RiskEngine()
