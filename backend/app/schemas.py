from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict

class RequestLogBase(BaseModel):
    client_id: str
    gateway_id: str
    path: str
    method: str
    status_code: int
    latency_ms: float
    risk_score: int
    decision: str
    reason: Optional[str] = None

class RequestLogCreate(RequestLogBase):
    pass

class RequestLogResponse(RequestLogBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class ClientStats(BaseModel):
    client_id: str
    requests_per_min: int
    risk_score: int
    status: str  # NORMAL, MONITORED, THROTTLED, BLOCKED
    current_limit: str  # e.g., "100/min"
    last_activity: datetime
    error_rate: float
    burstiness: float
    unique_endpoints: int
    reasons: List[str] = []

class GatewayStats(BaseModel):
    total_requests: int
    blocked_requests: int
    suspicious_clients: int
    active_clients: int
    requests_per_sec: float

class DashboardUpdate(BaseModel):
    stats: GatewayStats
    active_clients: List[ClientStats]
    recent_logs: List[RequestLogResponse]
    risk_distribution: Dict[str, float]  # NORMAL %, SUSPICIOUS %, BLOCKED %
    timestamp: datetime

class SimulatorConfig(BaseModel):
    type: str = "NORMAL"  # NORMAL, BURST, BOT, BRUTE_FORCE, DDOS
    requests_per_sec: float = 2.0
    duration: int = 60  # seconds
    num_clients: int = 1
    target_endpoint: str = "/backend/products"

class RateLimiterConfig(BaseModel):
    base_rate_limit: int
    token_bucket_capacity: int
    refill_rate_secs: float
    adaptive_enabled: bool = True
    risk_threshold_throttle: int
    risk_threshold_high_throttle: int
    risk_threshold_severe_throttle: int
    risk_threshold_block: int
