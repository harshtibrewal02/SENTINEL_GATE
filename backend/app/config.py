import os
import json
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sentinel_user:sentinel_pass@db:5432/sentinel_db"
    REDIS_URL: str = "redis://redis:6379/0"
    
    GATEWAY_ID: str = "gateway-1"
    PORT: int = 8000
    
    # Rate limiter defaults
    BASE_RATE_LIMIT: int = 100
    TOKEN_BUCKET_CAPACITY: int = 100
    REFILL_RATE_SECS: float = 60.0  # Refill base_rate_limit tokens every refill_rate_secs
    
    # Risk thresholds (0-100 score)
    RISK_THRESHOLD_THROTTLE: int = 30
    RISK_THRESHOLD_HIGH_THROTTLE: int = 60
    RISK_THRESHOLD_SEVERE_THROTTLE: int = 80
    RISK_THRESHOLD_BLOCK: int = 95
    
    # Anomaly detector
    ANOMALY_DETECTION_INTERVAL_SECS: int = 30
    MIN_TRAINING_SAMPLES: int = 20
    
    # Security
    SECRET_KEY: str = "super-secret-key-for-gate-session"
    CORS_ORIGINS: str = '["*"]'
    
    @property
    def cors_origins_list(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
