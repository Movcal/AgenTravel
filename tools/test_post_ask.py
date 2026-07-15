"""Test del fix 405: POST /ask debe funcionar igual que GET /ask. Modo sin pago."""
import os, sys, json
os.environ["OKX_API_KEY"] = ""   # forzar modo sin pago ANTES de importar
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import server
from fastapi.testclient import TestClient

client = TestClient(server.app)

# 1. POST sin parametros -> 400 (sin cobrar, sin Claude)
print("=== 1) POST /ask sin parametros -> 400 ===")
r = client.post("/ask")
print("HTTP", r.status_code, "-", r.json().get("error", "")[:80])
assert r.status_code == 400

# 2. POST con ciudad sin cobertura -> 404 (sin Claude)
print("\n=== 2) POST /ask ciudad sin cobertura -> 404 ===")
r = client.post("/ask", json={"city": "Miami", "query": "que hacer"})
print("HTTP", r.status_code, "-", r.json().get("error", "")[:80])
assert r.status_code == 404

# 3. POST con fecha invalida -> 400 (sin Claude)
print("\n=== 3) POST /ask fecha invalida -> 400 ===")
r = client.post("/ask", json={"city": "Paris", "query": "que hacer", "date": "15-07-2026"})
print("HTTP", r.status_code, "-", r.json().get("error", "")[:80])
assert r.status_code == 400

# 4. GET con ciudad sin cobertura -> 404 (el GET sigue cableado igual, sin Claude)
print("\n=== 4) GET /ask ciudad sin cobertura -> 404 ===")
r = client.get("/ask", params={"city": "Miami", "query": "que hacer"})
print("HTTP", r.status_code, "-", r.json().get("error", "")[:80])
assert r.status_code == 404

# 5. POST valido con body JSON (UNA consulta real a Claude, ~$0.03)
print("\n=== 5) POST /ask body JSON end-to-end (1 consulta real a Claude) ===")
r = client.post("/ask", json={
    "city": "Buenos Aires",
    "query": "what can I do today on a budget?",
})
print("HTTP", r.status_code)
data = r.json()
assert r.status_code == 200, data
assert data.get("research_proof"), "falta research_proof"
print("research_proof:", json.dumps(data["research_proof"], ensure_ascii=False))
print("response (primeros 300):", data["response"][:300])

print("\nTODO OK")
