"""
SentinelGate Deployment Readiness Check
Verifies all critical systems are working end-to-end.
"""
import httpx
import time
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://127.0.0.1:3000"

def check(name, passed, detail=""):
    icon = "[PASS]" if passed else "[FAIL]"
    msg = f"  {icon} {name}" + (f" -- {detail}" if detail else "")
    print(msg)
    return passed

def main():
    results = []
    c = httpx.Client(timeout=10)

    print("=" * 60)
    print("  SENTINELGATE DEPLOYMENT READINESS CHECK")
    print("=" * 60)

    # --- BACKEND HEALTH ---
    print("\n[1] BACKEND SERVER")
    try:
        r = c.get(f"{BACKEND}/health")
        j = r.json()
        results.append(check("Health endpoint", r.status_code == 200, f"gateway={j.get('gateway_id')}"))
        results.append(check("ML engine loaded", j.get("ml_engine_loaded") == True))
    except Exception as e:
        results.append(check("Backend reachable", False, str(e)))

    # --- GATEWAY ROUTING ---
    print("\n[2] GATEWAY ROUTING")
    headers = {"X-API-Key": "apikey-readiness-check"}
    try:
        for endpoint, method in [("products", "GET"), ("profile", "GET"), ("orders", "GET"), ("login", "POST"), ("search", "GET")]:
            if method == "POST":
                r = c.post(f"{BACKEND}/gateway/{endpoint}", headers=headers, json={})
            else:
                r = c.get(f"{BACKEND}/gateway/{endpoint}", headers=headers)
            has_risk = "X-Risk-Score" in r.headers
            has_limit = "X-RateLimit-Remaining" in r.headers
            results.append(check(f"/{endpoint} ({method})", r.status_code in [200, 401] and has_risk and has_limit,
                                 f"status={r.status_code} risk={r.headers.get('X-Risk-Score')} remaining={r.headers.get('X-RateLimit-Remaining')}"))
    except Exception as e:
        results.append(check("Gateway routing", False, str(e)))

    # --- ADAPTIVE RATE LIMITING ---
    print("\n[3] ADAPTIVE RATE LIMITING")
    headers2 = {"X-API-Key": "apikey-deploy-burst"}
    throttled = blocked = False
    try:
        for i in range(100):
            r = c.get(f"{BACKEND}/gateway/products", headers=headers2)
            if r.status_code == 429:
                throttled = True
            if r.status_code == 403:
                blocked = True
                break
            time.sleep(0.01)
        results.append(check("Token bucket throttling (429)", throttled))
        results.append(check("Risk-based blocking (403)", blocked))

        # Cooldown
        time.sleep(6)
        r = c.get(f"{BACKEND}/gateway/products", headers=headers2)
        recovered = r.status_code == 200
        results.append(check("Risk decay / cooldown recovery", recovered,
                             f"post-cooldown status={r.status_code} risk={r.headers.get('X-Risk-Score')}"))
    except Exception as e:
        results.append(check("Rate limiting", False, str(e)))

    # --- DASHBOARD API ---
    print("\n[4] DASHBOARD API ENDPOINTS")
    for path, label in [("/api/stats", "Stats"), ("/api/clients", "Clients list"),
                        ("/api/config", "Config"), ("/api/logs", "Logs")]:
        try:
            r = c.get(f"{BACKEND}{path}")
            results.append(check(f"{label} ({path})", r.status_code == 200))
        except Exception as e:
            results.append(check(f"{label}", False, str(e)))

    # --- SIMULATOR API ---
    print("\n[5] SIMULATOR API")
    try:
        r = c.post(f"{BACKEND}/api/simulation/start", json={
            "type": "NORMAL", "requests_per_sec": 2, "duration": 5,
            "num_clients": 1, "target_endpoint": "/backend/products"
        })
        results.append(check("Start simulation", r.status_code == 200))
        time.sleep(3)
        r = c.post(f"{BACKEND}/api/simulation/stop")
        results.append(check("Stop simulation", r.status_code == 200))
        r = c.get(f"{BACKEND}/api/simulation/status")
        results.append(check("Simulation status endpoint", r.status_code == 200))
    except Exception as e:
        results.append(check("Simulator", False, str(e)))

    # --- WEBSOCKET ---
    print("\n[6] WEBSOCKET")
    try:
        import websockets
        import asyncio
        async def ws_test():
            async with websockets.connect("ws://127.0.0.1:8000/ws/dashboard") as ws:
                await ws.send("ping")
                resp = await asyncio.wait_for(ws.recv(), timeout=3)
                return resp == "pong"
        ws_ok = asyncio.run(ws_test())
        results.append(check("WebSocket /ws/dashboard", ws_ok))
    except Exception as e:
        results.append(check("WebSocket", False, str(e)))

    # --- FRONTEND ---
    print("\n[7] FRONTEND")
    try:
        r = c.get(FRONTEND)
        has_root = "root" in r.text
        has_title = "SentinelGate" in r.text
        results.append(check("Frontend serves HTML", r.status_code == 200 and has_root, f"has_root={has_root} has_title={has_title}"))
    except Exception as e:
        results.append(check("Frontend reachable", False, str(e)))

    # --- SUMMARY ---
    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"  RESULT: {passed}/{total} checks passed")
    if passed == total:
        print("  >>> PROJECT IS DEPLOYMENT READY! <<<")
    else:
        failed = total - passed
        print(f"  !!! {failed} check(s) failed - review above")
    print("=" * 60)

    c.close()
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
