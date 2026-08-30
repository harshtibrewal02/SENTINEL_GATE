import random
from fastapi import APIRouter, Response, status, Query
from pydantic import BaseModel

router = APIRouter(prefix="/backend", tags=["mock_backend"])

class Product(BaseModel):
    id: int
    name: str
    price: float
    category: str

@router.get("/products")
def get_products():
    return [
        {"id": 1, "name": "SecureShield VPN", "price": 49.99, "category": "Security"},
        {"id": 2, "name": "SentinelGate Enterprise", "price": 299.99, "category": "Gateway"},
        {"id": 3, "name": "CyberThreat Analyzer", "price": 149.99, "category": "Analytics"},
        {"id": 4, "name": "LogDecrypt Pro", "price": 89.99, "category": "Logs"}
    ]

@router.get("/profile")
def get_profile():
    return {
        "user_id": "usr_99812",
        "username": "sec_ops_specialist",
        "email": "ops@sentinelgate.io",
        "role": "Administrator",
        "last_login": "2026-08-29T21:00:00Z"
    }

@router.get("/orders")
def get_orders():
    return [
        {"order_id": "ord_1001", "total": 349.98, "status": "completed"},
        {"order_id": "ord_1002", "total": 49.99, "status": "pending"}
    ]

@router.post("/login")
def post_login(response: Response):
    # Brute force attack will hit this endpoint.
    # Return 401 Unauthorized for simulation unless specified
    response.status_code = status.HTTP_401_UNAUTHORIZED
    return {"error": "Invalid API key or authentication credentials."}

@router.get("/search")
def get_search(q: str = Query("default")):
    return {
        "query": q,
        "results_count": 3,
        "results": [f"Result matching {q} #1", f"Result matching {q} #2", f"Result matching {q} #3"]
    }
