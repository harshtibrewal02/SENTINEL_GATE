import time
import logging
import json
from fastapi import APIRouter, Request, Response, BackgroundTasks, status
from typing import Optional
import asyncio

from app.config import settings
from app.database import SessionLocal
from app.models import RequestLog, SecurityEvent
from app.rate_limiter.redis_limiter import rate_limiter
from app.detection.feature_engine import feature_engine
from app.detection.risk_engine import risk_engine
from app.websocket.manager import manager

router = APIRouter(tags=["gateway"])
logger = logging.getLogger("gateway")

# ---- Mock Backend dispatch table ----
# Instead of proxying via HTTP (which causes self-connection issues),
# we dispatch directly to the backend logic functions.

MOCK_PRODUCTS = [
    {"id": 1, "name": "SecureShield VPN", "price": 49.99, "category": "Security"},
    {"id": 2, "name": "SentinelGate Enterprise", "price": 299.99, "category": "Gateway"},
    {"id": 3, "name": "CyberThreat Analyzer", "price": 149.99, "category": "Analytics"},
    {"id": 4, "name": "LogDecrypt Pro", "price": 89.99, "category": "Logs"}
]

MOCK_PROFILE = {
    "user_id": "usr_99812",
    "username": "sec_ops_specialist",
    "email": "ops@sentinelgate.io",
    "role": "Administrator",
    "last_login": "2026-08-29T21:00:00Z"
}

MOCK_ORDERS = [
    {"order_id": "ord_1001", "total": 349.98, "status": "completed"},
    {"order_id": "ord_1002", "total": 49.99, "status": "pending"}
]


def dispatch_backend(path: str, method: str, query_params: dict) -> tuple[int, dict]:
    """
    Directly dispatch to mock backend logic without making an HTTP call.
    Returns (status_code, response_body).
    """
    clean_path = path.strip("/")

    if clean_path == "products" or clean_path == "backend/products":
        return 200, MOCK_PRODUCTS
    elif clean_path == "profile" or clean_path == "backend/profile":
        return 200, MOCK_PROFILE
    elif clean_path == "orders" or clean_path == "backend/orders":
        return 200, MOCK_ORDERS
    elif clean_path == "login" or clean_path == "backend/login":
        if method == "POST":
            return 401, {"error": "Invalid API key or authentication credentials."}
        return 405, {"error": "Method not allowed"}
    elif clean_path == "search" or clean_path == "backend/search":
        q = query_params.get("q", "default")
        return 200, {
            "query": q,
            "results_count": 3,
            "results": [f"Result matching {q} #1", f"Result matching {q} #2", f"Result matching {q} #3"]
        }
    else:
        return 404, {"error": f"Backend endpoint /{clean_path} not found"}


def log_request_to_db(
    client_id: str,
    path: str,
    method: str,
    status_code: int,
    latency_ms: float,
    risk_score: int,
    decision: str,
    reason: Optional[str]
):
    db = SessionLocal()
    try:
        log_entry = RequestLog(
            client_id=client_id,
            gateway_id=settings.GATEWAY_ID,
            path=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            risk_score=risk_score,
            decision=decision,
            reason=reason
        )
        db.add(log_entry)
        db.commit()
        
        if decision == "BLOCK":
            event = SecurityEvent(
                client_id=client_id,
                event_type="CLIENT_BLOCKED",
                details=f"Client blocked with risk score {risk_score}. Path: {path}. Reasons: {reason}"
            )
            db.add(event)
            db.commit()
        elif risk_score >= settings.RISK_THRESHOLD_SEVERE_THROTTLE:
            event = SecurityEvent(
                client_id=client_id,
                event_type="SEVERE_THROTTLING_TRIGGERED",
                details=f"Client throttled (10 req/min) with risk score {risk_score}. Reasons: {reason}"
            )
            db.add(event)
            db.commit()
            
    except Exception as e:
        logger.error(f"Error logging request to DB: {e}")
    finally:
        db.close()


async def broadcast_log_update(
    client_id: str,
    path: str,
    method: str,
    status_code: int,
    latency_ms: float,
    risk_score: int,
    decision: str,
    reason: Optional[str]
):
    log_data = {
        "event": "new_log",
        "log": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": client_id,
            "gateway_id": settings.GATEWAY_ID,
            "path": path,
            "method": method,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 1),
            "risk_score": risk_score,
            "decision": decision,
            "reason": reason
        }
    }
    await manager.broadcast(log_data)


@router.api_route("/gateway/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def gateway_entry(path: str, request: Request, response: Response, background_tasks: BackgroundTasks):
    start_time = time.time()
    
    # 1. Identify Client
    client_id = request.headers.get("X-API-Key")
    if not client_id:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            client_id = xff.split(",")[0].strip()
        else:
            client_id = request.client.host if request.client else "unknown-client"
            
    if client_id.startswith("apikey-"):
        client_id = client_id.replace("apikey-", "")

    # 2. Retrieve features and calculate threat score
    features = await feature_engine.get_client_features(client_id)
    risk_score, reasons = await risk_engine.get_and_update_risk(client_id, features)
    
    # 3. Determine Adaptive Thresholds
    status_str = "NORMAL"
    rate_limit = settings.BASE_RATE_LIMIT
    
    if risk_score > settings.RISK_THRESHOLD_BLOCK:
        status_str = "BLOCKED"
        rate_limit = 0
    elif risk_score > settings.RISK_THRESHOLD_SEVERE_THROTTLE:
        status_str = "THROTTLED"
        rate_limit = 10
    elif risk_score > settings.RISK_THRESHOLD_HIGH_THROTTLE:
        status_str = "THROTTLED"
        rate_limit = 30
    elif risk_score > settings.RISK_THRESHOLD_THROTTLE:
        status_str = "MONITORED"
        rate_limit = 60

    reasons_str = "; ".join(reasons) if reasons else "None"

    response.headers["X-Risk-Score"] = str(risk_score)
    response.headers["X-Gateway-Status"] = status_str
    
    # 4. Handle Blocked State
    if status_str == "BLOCKED":
        latency = (time.time() - start_time) * 1000
        background_tasks.add_task(
            log_request_to_db, client_id, path, request.method, 403, latency, risk_score, "BLOCK", reasons_str
        )
        background_tasks.add_task(
            broadcast_log_update, client_id, path, request.method, 403, latency, risk_score, "BLOCK", reasons_str
        )
        await feature_engine.record_request(client_id, path, request.method, 403)
        
        response.status_code = status.HTTP_403_FORBIDDEN
        response.headers["X-RateLimit-Limit"] = "0"
        response.headers["X-RateLimit-Remaining"] = "0"
        return {"error": f"Access Denied: Client blocked. Threat Risk: {risk_score}. Reason: {reasons_str}"}

    # 5. Execute Token Bucket Rate Limit
    refill_rate_per_sec = rate_limit / 60.0
    allowed, tokens_remaining = await rate_limiter.is_allowed(
        client_id, capacity=rate_limit, refill_rate_per_sec=refill_rate_per_sec, cost=1
    )
    
    response.headers["X-RateLimit-Limit"] = str(rate_limit)
    response.headers["X-RateLimit-Remaining"] = str(int(tokens_remaining))

    if not allowed:
        latency = (time.time() - start_time) * 1000
        background_tasks.add_task(
            log_request_to_db, client_id, path, request.method, 429, latency, risk_score, "THROTTLE", "Rate limit exceeded"
        )
        background_tasks.add_task(
            broadcast_log_update, client_id, path, request.method, 429, latency, risk_score, "THROTTLE", "Rate limit exceeded"
        )
        await feature_engine.record_request(client_id, path, request.method, 429)
        
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = "5"
        return {"error": "Too Many Requests. Rate limit exceeded for risk tier."}

    # 6. Dispatch directly to mock backend (no httpx proxy needed)
    query_params = dict(request.query_params)
    backend_status, backend_body = dispatch_backend(path, request.method, query_params)

    latency = (time.time() - start_time) * 1000

    # 7. Record Request and Log results
    await feature_engine.record_request(client_id, path, request.method, backend_status)
    background_tasks.add_task(
        log_request_to_db, client_id, path, request.method, backend_status, latency, risk_score, "ALLOW", reasons_str
    )
    background_tasks.add_task(
        broadcast_log_update, client_id, path, request.method, backend_status, latency, risk_score, "ALLOW", reasons_str
    )

    # 8. Construct response
    response.status_code = backend_status
    return backend_body
