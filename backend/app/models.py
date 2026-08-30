from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from app.database import Base

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    client_id = Column(String(100), index=True, nullable=False)
    gateway_id = Column(String(50), nullable=False)
    path = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    latency_ms = Column(Float, nullable=False)
    risk_score = Column(Integer, nullable=False)
    decision = Column(String(20), nullable=False)  # ALLOW, THROTTLE, BLOCK
    reason = Column(Text, nullable=True)

class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    client_id = Column(String(100), index=True, nullable=False)
    event_type = Column(String(50), nullable=False)  # BLOCK_TRIGGERED, HIGH_RISK_DETECTED, etc.
    details = Column(Text, nullable=True)
