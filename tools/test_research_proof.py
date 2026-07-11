"""Test del Paso 3: comprobante de investigacion. Modo sin pago."""
import os, sys, json
os.environ["OKX_API_KEY"] = ""   # forzar modo sin pago ANTES de importar
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import server

# 1. get_db_context devuelve (context, stats) sin llamar a Claude (gratis)
print("=== 1) get_db_context stats (sin Claude) ===")
for city in ["Buenos Aires", "Paris"]:
    ctx, stats = server.get_db_context(city, None)
    print(city, "->", json.dumps(stats, ensure_ascii=False))

# 2. UNA consulta real a /ask (SI llama a Claude, ~$0.03)
print("\n=== 2) /ask end-to-end (1 consulta real a Claude) ===")
from fastapi.testclient import TestClient
client = TestClient(server.app)
r = client.get("/ask", params={
    "city": "Buenos Aires",
    "query": "que puedo hacer hoy con presupuesto limitado",
})
print("HTTP", r.status_code)
data = r.json()
print("research_proof:", json.dumps(data.get("research_proof"), ensure_ascii=False, indent=2))
print("\nresponse (primeros 300):", (data.get("response") or data)[:300] if isinstance(data.get("response"), str) else data)
