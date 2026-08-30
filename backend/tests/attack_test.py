import httpx, time

c = httpx.Client(base_url='http://127.0.0.1:8000', timeout=10)
headers = {'X-API-Key': 'apikey-heavy-attacker'}
print('=== Heavy Attack: 150 requests ===')
blocked_at = throttled_at = None
for i in range(150):
    r = c.get('/gateway/products', headers=headers)
    risk = r.headers.get('X-Risk-Score', '?')
    if r.status_code == 429 and not throttled_at:
        throttled_at = i+1
        print(f'  THROTTLED at request {throttled_at}! Risk={risk}')
    elif r.status_code == 403 and not blocked_at:
        blocked_at = i+1
        print(f'  BLOCKED at request {blocked_at}! Risk={risk}')
        break
    elif i % 25 == 0:
        print(f'  [{i+1}] status={r.status_code} risk={risk}')
    time.sleep(0.01)

if not throttled_at and not blocked_at:
    print('  No throttle/block triggered - need to tune thresholds')
else:
    print(f'  Throttle at: {throttled_at}, Block at: {blocked_at}')

# Cooldown test
print('')
print('=== Cooldown: waiting 10s ===')
time.sleep(10)
r = c.get('/gateway/products', headers=headers)
risk_after = r.headers.get('X-Risk-Score', '?')
print(f'  After cooldown: status={r.status_code} risk={risk_after}')
print('Done.')
