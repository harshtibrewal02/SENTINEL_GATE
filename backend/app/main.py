import logging
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.websocket.manager import manager
from app.rate_limiter.redis_limiter import rate_limiter
from app.detection.anomaly_detector import anomaly_detector
from app.detection.risk_engine import risk_engine
from app.detection.feature_engine import feature_engine
from app.simulation.simulator import simulator

# Import routes
from app.routes import gateway, mock_backend, api

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

# Background tasks references to prevent GC
background_tasks = set()

async def websocket_broadcast_loop():
    """
    Background loop to broadcast system updates to the React dashboard WebSockets at 1Hz.
    """
    logger.info("Starting WebSocket broadcast background loop...")
    while True:
        await asyncio.sleep(1.0)
        
        # Only broadcast if there are active dashboard sessions
        if not manager.active_connections:
            # We still run background decay for clients even if dashboard is closed
            try:
                active_ids = await feature_engine.get_active_clients()
                for cid in active_ids:
                    # Decay client risks slowly
                    await risk_engine.decay_client_risk_background(cid)
            except Exception:
                pass
            continue

        db = SessionLocal()
        try:
            # Aggregate stats & fetch clients
            from sqlalchemy import func, case
            from app.models import RequestLog
            from datetime import datetime

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
            clients_list = []
            normal_c, susp_c, blocked_c = 0, 0, 0
            total_rps = 0.0

            for cid in active_ids:
                # Decays risk automatically when updating/checking
                features = await feature_engine.get_client_features(cid)
                risk_score, reasons = await risk_engine.get_and_update_risk(cid, features)
                
                status_str = "NORMAL"
                limit_str = f"{settings.BASE_RATE_LIMIT}/min"
                
                if risk_score > settings.RISK_THRESHOLD_BLOCK:
                    status_str = "BLOCKED"
                    limit_str = "0/min"
                    blocked_c += 1
                elif risk_score > settings.RISK_THRESHOLD_THROTTLE:
                    status_str = "THROTTLED"
                    limit_str = "30/min"
                    susp_c += 1
                    suspicious_count += 1
                else:
                    status_str = "NORMAL"
                    normal_c += 1

                total_rps += features.get("rps", 0.0)

                # Format timestamp for JSON serialization
                last_act = datetime.fromtimestamp(features.get("last_activity", datetime.utcnow().timestamp()))

                clients_list.append({
                    "client_id": cid,
                    "requests_per_min": features.get("rpm", 0),
                    "risk_score": risk_score,
                    "status": status_str,
                    "current_limit": limit_str,
                    "last_activity": last_act.strftime("%Y-%m-%d %H:%M:%S"),
                    "error_rate": round(features.get("error_rate", 0.0), 2),
                    "burstiness": round(features.get("burstiness", 0.0), 4),
                    "unique_endpoints": features.get("unique_endpoints", 0),
                    "reasons": reasons
                })

            clients_list.sort(key=lambda x: x["risk_score"], reverse=True)

            total_tracked = normal_c + susp_c + blocked_c
            if total_tracked > 0:
                risk_dist = {
                    "NORMAL": round(normal_c / total_tracked * 100, 1),
                    "SUSPICIOUS": round(susp_c / total_tracked * 100, 1),
                    "BLOCKED": round(blocked_c / total_tracked * 100, 1)
                }
            else:
                risk_dist = {"NORMAL": 100.0, "SUSPICIOUS": 0.0, "BLOCKED": 0.0}

            # Fetch recent 20 logs
            recent_logs = db.query(RequestLog).order_by(RequestLog.timestamp.desc()).limit(20).all()
            logs_list = []
            for l in recent_logs:
                logs_list.append({
                    "id": l.id,
                    "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "client_id": l.client_id,
                    "gateway_id": l.gateway_id,
                    "path": l.path,
                    "method": l.method,
                    "status_code": l.status_code,
                    "latency_ms": round(l.latency_ms, 1),
                    "risk_score": l.risk_score,
                    "decision": l.decision,
                    "reason": l.reason
                })

            update_payload = {
                "event": "dashboard_update",
                "stats": {
                    "total_requests": total_reqs,
                    "blocked_requests": blocked_reqs,
                    "suspicious_clients": suspicious_count,
                    "active_clients": active_clients_count,
                    "requests_per_sec": round(total_rps, 2)
                },
                "active_clients": clients_list,
                "recent_logs": logs_list,
                "risk_distribution": risk_dist,
                "simulator": simulator.get_status(),
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }

            await manager.broadcast(update_payload)
        except Exception as e:
            logger.error(f"Error in WebSocket broadcast loop: {e}")
        finally:
            db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Create SQL DB Tables
    logger.info("Initializing database schemas...")
    Base.metadata.create_all(bind=engine)
    
    # Initialize Lua scripts in Redis
    logger.info("Initializing Redis scripts...")
    await rate_limiter.initialize()
    
    # Start Anomaly Detection ML retraining loop in background
    logger.info("Spawning background tasks...")
    anomaly_task = asyncio.create_task(anomaly_detector.train_loop())
    background_tasks.add(anomaly_task)
    anomaly_task.add_done_callback(background_tasks.discard)

    # Start WebSocket publisher loop in background
    ws_pub_task = asyncio.create_task(websocket_broadcast_loop())
    background_tasks.add(ws_pub_task)
    ws_pub_task.add_done_callback(background_tasks.discard)

    yield
    # --- Shutdown ---
    logger.info("Shutting down background tasks...")
    await simulator.stop()
    for task in background_tasks:
        task.cancel()
    logger.info("Shutdown sequence complete.")

# Initialize FastAPI App
app = FastAPI(
    title="SentinelGate API Gateway",
    description="Adaptive Rate-Limiting & Abuse Detection Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(gateway.router)
app.include_router(mock_backend.router)
app.include_router(api.router)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "gateway_id": settings.GATEWAY_ID,
        "ml_engine_loaded": anomaly_detector.is_trained
    }

@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Keep client connection open
        while True:
            # We can optionally listen to triggers or requests from client here
            data = await websocket.receive_text()
            # If dashboard sends a ping, reply with pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client communication error: {e}")
        await manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    import os
    # Read port from environment if present, else fallback to settings
    port = int(os.getenv("PORT", settings.PORT))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
