import asyncio
import random
import logging
import httpx
import time
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger("simulator")

class TrafficSimulator:
    def __init__(self):
        self.active_task: Optional[asyncio.Task] = None
        self.running = False
        self.sim_type = "NORMAL"
        self.stats = {
            "requests_generated": 0,
            "requests_allowed": 0,
            "requests_throttled": 0,
            "requests_blocked": 0,
            "current_rate": 0.0
        }
        self.start_time = 0.0

    async def start(self, sim_type: str, requests_per_sec: float, duration: int, num_clients: int, target_endpoint: str):
        await self.stop()
        
        self.running = True
        self.sim_type = sim_type
        self.stats = {
            "requests_generated": 0,
            "requests_allowed": 0,
            "requests_throttled": 0,
            "requests_blocked": 0,
            "current_rate": requests_per_sec
        }
        self.start_time = time.time()
        
        # Spawn the background task
        self.active_task = asyncio.create_task(
            self._run_simulation(sim_type, requests_per_sec, duration, num_clients, target_endpoint)
        )
        logger.info(f"Traffic simulation '{sim_type}' started with rate {requests_per_sec} req/s, target: {target_endpoint}")

    async def stop(self):
        self.running = False
        if self.active_task:
            self.active_task.cancel()
            try:
                await self.active_task
            except asyncio.CancelledError:
                pass
            self.active_task = None
            logger.info("Traffic simulation stopped.")

    async def _run_simulation(self, sim_type: str, rps: float, duration: int, num_clients: int, target_endpoint: str):
        client = httpx.AsyncClient()
        interval = 1.0 / rps if rps > 0 else 0.5
        
        endpoints = [
            "products",
            "profile",
            "orders",
            "search",
            "login"
        ]

        try:
            while self.running and (time.time() - self.start_time < duration):
                # Determine Client ID(s)
                if sim_type == "NORMAL":
                    client_id = "client-normal-01"
                    path = f"backend/{random.choice(endpoints[:-1])}" # normal users rarely brute force
                    method = "GET"
                elif sim_type == "BURST":
                    client_id = "client-burst-02"
                    path = f"backend/{random.choice(endpoints[:-1])}"
                    method = "GET"
                elif sim_type == "BOT":
                    client_id = "client-bot-03"
                    path = f"backend/products" # scrapers hit the same product catalog
                    method = "GET"
                elif sim_type == "BRUTE_FORCE":
                    client_id = "client-brute-04"
                    path = "backend/login" # brute force target login
                    method = "POST"
                elif sim_type == "DDOS":
                    # DDoS uses multiple clients
                    client_index = random.randint(1, num_clients)
                    client_id = f"client-ddos-{client_index:02d}"
                    path = f"backend/{random.choice(endpoints)}"
                    method = "GET" if path != "backend/login" else "POST"
                else:
                    client_id = "client-generic"
                    path = "backend/products"
                    method = "GET"

                # If custom target endpoint is given, use it (strip leading slash)
                clean_target = target_endpoint.lstrip("/")
                if clean_target.startswith("gateway/"):
                    clean_target = clean_target[8:]
                if clean_target:
                    path = clean_target

                # Prepare the request to our Gateway route
                # We hit the dynamic port configured in settings
                url = f"http://127.0.0.1:{settings.PORT}/gateway/{path}"
                headers = {
                    "X-API-Key": f"apikey-{client_id}",
                    "X-Forwarded-For": f"192.168.1.{random.randint(10, 200)}"
                }

                # Schedule request execution asynchronously without blocking the loop
                asyncio.create_task(self._send_request(client, method, url, headers))

                self.stats["requests_generated"] += 1
                await asyncio.sleep(interval)

        except Exception as e:
            logger.error(f"Simulator exception: {e}")
        finally:
            await client.aclose()
            self.running = False
            logger.info("Simulation run completed.")

    async def _send_request(self, client: httpx.AsyncClient, method: str, url: str, headers: dict):
        try:
            if method == "POST":
                resp = await client.post(url, headers=headers, json={"user": "admin", "password": "wrongpassword"}, timeout=5.0)
            else:
                resp = await client.get(url, headers=headers, timeout=5.0)

            # Record stats based on response headers or status codes
            # Our gateway will return rate limit remaining or specific custom headers
            # X-Risk-Score: 80
            # If status code is 429 -> throttled. If 403 -> blocked. Else allowed.
            if resp.status_code == 429:
                self.stats["requests_throttled"] += 1
            elif resp.status_code == 403:
                self.stats["requests_blocked"] += 1
            else:
                self.stats["requests_allowed"] += 1

        except Exception as e:
            logger.error(f"Simulator request failed: {e}")
            self.stats["requests_blocked"] += 1 # consider failed connections as blocked/dropped

    def get_status(self) -> Dict[str, Any]:
        elapsed = time.time() - self.start_time if self.running else 0.0
        return {
            "running": self.running,
            "sim_type": self.sim_type,
            "elapsed_seconds": int(elapsed),
            "stats": self.stats
        }

simulator = TrafficSimulator()
