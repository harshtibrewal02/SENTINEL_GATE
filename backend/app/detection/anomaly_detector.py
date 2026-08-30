import logging
import asyncio
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Any
from app.config import settings
from app.database import SessionLocal
from app.models import RequestLog
from sqlalchemy import func, case

logger = logging.getLogger("anomaly_detector")

class AnomalyDetector:
    def __init__(self):
        self.model = None
        self.is_trained = False
        self.features_list = [
            "rpm", "rps", "burstiness", "error_rate", 
            "unique_endpoints", "max_endpoint_repeat_ratio", "traffic_spike_ratio"
        ]
        self._initialize_baseline_model()

    def _initialize_baseline_model(self):
        """
        Seeds the Isolation Forest with synthetically generated 'normal' API traffic 
        to ensure it works instantly, even on first startup.
        """
        logger.info("Initializing baseline Isolation Forest model with synthetic normal data...")
        np.random.seed(42)
        n_samples = 100
        
        rpms = np.random.uniform(5, 30, n_samples)
        rpss = rpms / 60.0 + np.random.uniform(0, 0.5, n_samples)
        burstiness = np.random.exponential(0.1, n_samples)
        error_rates = np.random.beta(1, 20, n_samples)
        unique_eps = np.random.randint(1, 5, n_samples).astype(float)
        repeat_ratios = np.random.uniform(0.2, 0.6, n_samples)
        spikes = np.random.uniform(0.8, 1.3, n_samples)

        X_train = np.column_stack((rpms, rpss, burstiness, error_rates, unique_eps, repeat_ratios, spikes))
        
        self.model = IsolationForest(contamination=0.05, random_state=42)
        self.model.fit(X_train)
        self.is_trained = True
        logger.info("Baseline Isolation Forest model fitted successfully.")

    async def train_loop(self):
        """
        Background loop to fit/update the Isolation Forest using database historical records.
        """
        while True:
            await asyncio.sleep(settings.ANOMALY_DETECTION_INTERVAL_SECS)
            try:
                await self.retrain_model()
            except Exception as e:
                logger.error(f"Error in anomaly detector training loop: {e}")

    async def retrain_model(self):
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._query_aggregates_from_db)
        
        if len(data) < settings.MIN_TRAINING_SAMPLES:
            logger.info(f"Not enough real traffic data in DB ({len(data)}/{settings.MIN_TRAINING_SAMPLES}). Sticking with current model.")
            return

        logger.info(f"Retraining Isolation Forest model on {len(data)} data samples from DB...")
        
        X_train = np.array(data)
        try:
            new_model = IsolationForest(contamination=0.05, random_state=42)
            await loop.run_in_executor(None, new_model.fit, X_train)
            self.model = new_model
            self.is_trained = True
            logger.info("Isolation Forest retrained successfully on production data.")
        except Exception as e:
            logger.error(f"Failed to fit Isolation Forest: {e}")

    def _query_aggregates_from_db(self) -> List[List[float]]:
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=1)
            
            logs = db.query(
                RequestLog.client_id,
                func.count(RequestLog.id).label("rpm"),
                func.sum(
                    case(
                        (RequestLog.status_code >= 400, 1),
                        else_=0
                    )
                ).label("errors"),
                func.count(func.distinct(RequestLog.path)).label("unique_paths")
            ).filter(
                RequestLog.timestamp >= cutoff
            ).group_by(
                RequestLog.client_id
            ).all()

            samples = []
            for item in logs:
                rpm = float(item.rpm)
                rps = rpm / 60.0
                error_count = float(item.errors) if item.errors else 0.0
                error_rate = error_count / rpm if rpm > 0 else 0.0
                unique_eps = float(item.unique_paths)
                
                burstiness = 0.1
                repeat_ratio = 0.5
                spike_ratio = 1.0
                
                samples.append([rpm, rps, burstiness, error_rate, unique_eps, repeat_ratio, spike_ratio])
            return samples
        except Exception as e:
            logger.error(f"DB aggregation query failed: {e}")
            return []
        finally:
            db.close()

    def get_anomaly_score(self, features: Dict[str, Any]) -> float:
        if not self.is_trained or not self.model:
            return 0.0

        vector = [float(features.get(f, 0.0)) for f in self.features_list]
        vector_arr = np.array([vector])

        try:
            raw_score = self.model.decision_function(vector_arr)[0]
            anomaly_score = (0.1 - raw_score) / 0.4 * 100
            anomaly_score = np.clip(anomaly_score, 0.0, 100.0)
            return float(anomaly_score)
        except Exception as e:
            logger.error(f"Error during anomaly scoring: {e}")
            return 0.0

anomaly_detector = AnomalyDetector()
