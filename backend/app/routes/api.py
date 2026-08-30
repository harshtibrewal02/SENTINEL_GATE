import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List, Dict, Any, Optional
import json

from app.database import get_db
from app.models import RequestLog, SecurityEvent
from app.schemas import RequestLogResponse, ClientStats, GatewayStats, SimulatorConfig, RateLimiterConfig
from app.config import settings
from app.rate_limiter.redis_limiter import redis_client
from app.detection.feature_engine import feature_engine
from app.detection.risk_engine import risk_engine
from app.simulation.simulator import simulator

router = APIRouter(prefix="/api", tags=["dashboard_api"])
logger = logging.getLogger("dashboard_api")

@router.get("/stats", response_model=GatewayStats)
async def get_stats(db: Session = Depends(get_db)):
    try:
        totals = db.query(
            func.count(RequestLog.id).label("total"),
            func.sum(
                case(
                    (RequestLog.decision == "BLOCK", 1),
                    else_=0
                )
            ).label("blocked")
        ).first()
        
        total_reqs = totals.total if totals and totals.total else 0
        blocked_reqs = int(totals.blocked) if totals and totals.blocked else 0

        active_ids = await feature_engine.get_active_clients()
        active_clients_count = len(active_ids)

        suspicious_count = 0
        for cid in active_ids:
            risk_val = await redis_client.hget(f"client_risk:{cid}", "score")
            if risk_val and float(risk_val) > 30.0:
                suspicious_count += 1

        total_rps = 0.0
        for cid in active_ids:
            features = await feature_engine.get_client_features(cid)
            total_rps += features.get("rps", 0.0)

        return GatewayStats(
            total_requests=total_reqs,
            blocked_requests=blocked_reqs,
            suspicious_clients=suspicious_count,
            active_clients=active_clients_count,
            requests_per_sec=round(total_rps, 2)
        )
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return GatewayStats(total_requests=0, blocked_requests=0, suspicious_clients=0, active_clients=0, requests_per_sec=0.0)

@router.get("/clients", response_model=List[ClientStats])
async def get_clients():
    active_ids = await feature_engine.get_active_clients()
    clients = []
    
    for cid in active_ids:
        features = await feature_engine.get_client_features(cid)
        risk_score, reasons = await risk_engine.get_and_update_risk(cid, features)
        
        status_str = "NORMAL"
        limit_str = f"{settings.BASE_RATE_LIMIT}/min"
        
        if risk_score > settings.RISK_THRESHOLD_BLOCK:
            status_str = "BLOCKED"
            limit_str = "0/min"
        elif risk_score > settings.RISK_THRESHOLD_SEVERE_THROTTLE:
            status_str = "THROTTLED"
            limit_str = "10/min"
        elif risk_score > settings.RISK_THRESHOLD_HIGH_THROTTLE:
            status_str = "THROTTLED"
            limit_str = "30/min"
        elif risk_score > settings.RISK_THRESHOLD_THROTTLE:
            status_str = "MONITORED"
            limit_str = "60/min"

        last_act_ts = features.get("last_activity", datetime.utcnow().timestamp())
        clients.append(ClientStats(
            client_id=cid,
            requests_per_min=features.get("rpm", 0),
            risk_score=risk_score,
            status=status_str,
            current_limit=limit_str,
            last_activity=datetime.fromtimestamp(last_act_ts),
            error_rate=round(features.get("error_rate", 0.0), 2),
            burstiness=round(features.get("burstiness", 0.0), 4),
            unique_endpoints=features.get("unique_endpoints", 0),
            reasons=reasons
        ))
    
    clients.sort(key=lambda x: x.risk_score, reverse=True)
    return clients

@router.get("/clients/{client_id}", response_model=ClientStats)
async def get_client_detail(client_id: str):
    features = await feature_engine.get_client_features(client_id)
    risk_score, reasons = await risk_engine.get_and_update_risk(client_id, features)
    
    status_str = "NORMAL"
    limit_str = f"{settings.BASE_RATE_LIMIT}/min"
    
    if risk_score > settings.RISK_THRESHOLD_BLOCK:
        status_str = "BLOCKED"
        limit_str = "0/min"
    elif risk_score > settings.RISK_THRESHOLD_SEVERE_THROTTLE:
        status_str = "THROTTLED"
        limit_str = "10/min"
    elif risk_score > settings.RISK_THRESHOLD_HIGH_THROTTLE:
        status_str = "THROTTLED"
        limit_str = "30/min"
    elif risk_score > settings.RISK_THRESHOLD_THROTTLE:
        status_str = "MONITORED"
        limit_str = "60/min"

    return ClientStats(
        client_id=client_id,
        requests_per_min=features.get("rpm", 0),
        risk_score=risk_score,
        status=status_str,
        current_limit=limit_str,
        last_activity=datetime.fromtimestamp(features.get("last_activity", datetime.utcnow().timestamp())),
        error_rate=features.get("error_rate", 0.0),
        burstiness=features.get("burstiness", 0.0),
        unique_endpoints=features.get("unique_endpoints", 0),
        reasons=reasons
    )

@router.get("/logs", response_model=List[RequestLogResponse])
def get_logs(client_id: Optional[str] = None, decision: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(RequestLog)
    if client_id:
        query = query.filter(RequestLog.client_id == client_id)
    if decision:
        query = query.filter(RequestLog.decision == decision)
        
    logs = query.order_by(RequestLog.timestamp.desc()).limit(limit).all()
    return logs

@router.get("/config", response_model=RateLimiterConfig)
def get_config():
    return RateLimiterConfig(
        base_rate_limit=settings.BASE_RATE_LIMIT,
        token_bucket_capacity=settings.TOKEN_BUCKET_CAPACITY,
        refill_rate_secs=settings.REFILL_RATE_SECS,
        risk_threshold_throttle=settings.RISK_THRESHOLD_THROTTLE,
        risk_threshold_high_throttle=settings.RISK_THRESHOLD_HIGH_THROTTLE,
        risk_threshold_severe_throttle=settings.RISK_THRESHOLD_SEVERE_THROTTLE,
        risk_threshold_block=settings.RISK_THRESHOLD_BLOCK
    )

@router.post("/config")
def update_config(config: RateLimiterConfig):
    settings.BASE_RATE_LIMIT = config.base_rate_limit
    settings.TOKEN_BUCKET_CAPACITY = config.token_bucket_capacity
    settings.REFILL_RATE_SECS = config.refill_rate_secs
    settings.RISK_THRESHOLD_THROTTLE = config.risk_threshold_throttle
    settings.RISK_THRESHOLD_HIGH_THROTTLE = config.risk_threshold_high_throttle
    settings.RISK_THRESHOLD_SEVERE_THROTTLE = config.risk_threshold_severe_throttle
    settings.RISK_THRESHOLD_BLOCK = config.risk_threshold_block
    logger.info("Dynamic configuration values updated successfully.")
    return {"status": "success", "message": "Configuration updated successfully"}

@router.post("/simulation/start")
async def start_simulation(config: SimulatorConfig):
    await simulator.start(
        sim_type=config.type,
        requests_per_sec=config.requests_per_sec,
        duration=config.duration,
        num_clients=config.num_clients,
        target_endpoint=config.target_endpoint
    )
    return {"status": "success", "message": f"{config.type} simulation started."}

@router.post("/simulation/stop")
async def stop_simulation():
    await simulator.stop()
    return {"status": "success", "message": "Simulation stopped."}

@router.get("/simulation/status")
async def simulation_status():
    return simulator.get_status()
