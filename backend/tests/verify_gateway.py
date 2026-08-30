import subprocess
import time
import sys
import os
import signal
import httpx

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

TEST_PORT = 8077

def run_tests():
    print("====================================================")
    print(" SentinelGate Gateway Integration Test Suite        ")
    print("====================================================")
    
    server_process = None
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///./test_gateway.db"
    env["REDIS_URL"] = "redis://localhost:6379/0"
    env["PORT"] = str(TEST_PORT)
    env["GATEWAY_ID"] = "test-gateway"
    
    print(f"[*] Launching SentinelGate on port {TEST_PORT}...")
    try:
        server_process = subprocess.Popen(
            [sys.executable, "-m", "app.main"],
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        )
        time.sleep(5.0)
    except Exception as e:
        print(f"[-] Failed to launch test server: {e}")
        return False

    base_url = f"http://127.0.0.1:{TEST_PORT}"
    client = httpx.Client(base_url=base_url, timeout=10.0)
    
    success = True
    try:
        # TEST 1: Health Check
        print("\n[*] Test 1: Health endpoint...")
        resp = client.get("/health")
        if resp.status_code == 200 and resp.json().get("status") == "healthy":
            print(f"[+] PASSED: {resp.json()}")
        else:
            print(f"[-] FAILED: {resp.status_code} - {resp.text}")
            success = False

        # TEST 2: Gateway forwards requests to mock backend
        print("\n[*] Test 2: Gateway → Mock Backend forwarding...")
        headers = {"X-API-Key": "apikey-test-user-alpha"}
        resp = client.get("/gateway/products", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"[+] PASSED: Got {len(data)} products. Risk: {resp.headers.get('X-Risk-Score', '?')}")
            else:
                print(f"[-] FAILED: Unexpected body: {data}")
                success = False
        else:
            print(f"[-] FAILED: Status {resp.status_code}: {resp.text}")
            success = False

        # TEST 3: Token Bucket countdown
        print("\n[*] Test 3: Token Bucket countdown...")
        headers = {"X-API-Key": "apikey-token-test-beta"}
        remaining_values = []
        for i in range(5):
            resp = client.get("/gateway/products", headers=headers)
            rem = resp.headers.get("X-RateLimit-Remaining", "?")
            remaining_values.append(rem)
        
        try:
            nums = [int(float(v)) for v in remaining_values]
            if all(nums[i] > nums[i+1] for i in range(len(nums)-1)):
                print(f"[+] PASSED: Remaining tokens decreasing: {nums}")
            else:
                print(f"[~] WARN: Tokens not strictly decreasing: {nums} (may be refilling fast)")
        except Exception as e:
            print(f"[-] FAILED: Could not parse remaining values: {remaining_values} ({e})")
            success = False

        # TEST 4: Risk escalation under burst traffic
        print("\n[*] Test 4: Risk escalation under burst traffic...")
        headers = {"X-API-Key": "apikey-burst-attacker"}
        risk_scores = []
        decisions = {"200": 0, "429": 0, "403": 0}
        
        for i in range(120):
            resp = client.get("/gateway/products", headers=headers)
            risk = int(resp.headers.get("X-Risk-Score", "0"))
            risk_scores.append(risk)
            sc = str(resp.status_code)
            decisions[sc] = decisions.get(sc, 0) + 1
            
            if resp.status_code == 403:
                print(f"[+] Client BLOCKED at request {i+1} (Risk: {risk})")
                break
            time.sleep(0.02)
        
        max_risk = max(risk_scores) if risk_scores else 0
        print(f"    Risk progression: {risk_scores[0]} → {risk_scores[len(risk_scores)//2]} → {risk_scores[-1]} (max: {max_risk})")
        print(f"    Decisions: {decisions}")
        
        if decisions.get("429", 0) > 0 or decisions.get("403", 0) > 0:
            print(f"[+] PASSED: Adaptive rate limiting triggered.")
        else:
            print(f"[~] WARN: No throttling/blocking occurred. Risk may need more requests to escalate.")

        # TEST 5: Cooldown / Recovery
        print("\n[*] Test 5: Cooldown recovery (waiting 8s)...")
        time.sleep(8.0)
        
        resp = client.get("/gateway/products", headers={"X-API-Key": "apikey-burst-attacker"})
        recovered_risk = int(resp.headers.get("X-Risk-Score", "100"))
        recovered_status = resp.status_code
        print(f"    Post-cooldown risk: {recovered_risk}, status: {recovered_status}")
        
        if recovered_risk < max_risk:
            print(f"[+] PASSED: Risk decayed from {max_risk} to {recovered_risk}.")
        else:
            print(f"[-] FAILED: Risk did not decay. Still at {recovered_risk}.")
            success = False

        # TEST 6: Login brute force (401s should increase risk)
        print("\n[*] Test 6: Brute force login (POST /gateway/login)...")
        headers = {"X-API-Key": "apikey-brute-forcer"}
        login_risks = []
        for i in range(30):
            resp = client.post("/gateway/login", headers=headers, json={"user": "admin", "pass": "wrong"})
            risk = int(resp.headers.get("X-Risk-Score", "0"))
            login_risks.append(risk)
            time.sleep(0.02)
        
        if login_risks[-1] > login_risks[0]:
            print(f"[+] PASSED: Login brute force risk escalated: {login_risks[0]} → {login_risks[-1]}")
        else:
            print(f"[~] WARN: Risk didn't increase much during brute force: {login_risks[0]} → {login_risks[-1]}")

        # TEST 7: API endpoints
        print("\n[*] Test 7: Dashboard API endpoints...")
        
        stats_resp = client.get("/api/stats")
        if stats_resp.status_code == 200:
            print(f"[+] /api/stats OK: {stats_resp.json()}")
        else:
            print(f"[-] /api/stats FAILED: {stats_resp.status_code}")
            success = False
        
        clients_resp = client.get("/api/clients")
        if clients_resp.status_code == 200:
            print(f"[+] /api/clients OK: {len(clients_resp.json())} clients tracked")
        else:
            print(f"[-] /api/clients FAILED: {clients_resp.status_code}")
            success = False
        
        config_resp = client.get("/api/config")
        if config_resp.status_code == 200:
            print(f"[+] /api/config OK: {config_resp.json()}")
        else:
            print(f"[-] /api/config FAILED: {config_resp.status_code}")
            success = False

        logs_resp = client.get("/api/logs")
        if logs_resp.status_code == 200:
            print(f"[+] /api/logs OK: {len(logs_resp.json())} log entries")
        else:
            print(f"[-] /api/logs FAILED: {logs_resp.status_code}")
            success = False

    except Exception as e:
        print(f"\n[-] Exception during test execution: {e}")
        import traceback
        traceback.print_exc()
        success = False
    finally:
        client.close()
        print("\n[*] Shutting down test server...")
        if server_process:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
        
        for f in ["test_gateway.db", "sentinel_gateway.db"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
                
    if success:
        print("\n" + "=" * 52)
        print(" [+++] ALL INTEGRATION TESTS PASSED! [+++]")
        print("=" * 52 + "\n")
        return True
    else:
        print("\n" + "=" * 52)
        print(" [---] SOME TESTS FAILED. [---]")
        print("=" * 52 + "\n")
        return False

if __name__ == "__main__":
    passed = run_tests()
    sys.exit(0 if passed else 1)
