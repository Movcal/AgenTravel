"""Test del Paso 4: itinerario multi-dia. Modo sin pago. 1 sola consulta real."""
import os, sys, json
os.environ["OKX_API_KEY"] = ""   # modo sin pago ANTES de importar
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import server
from fastapi.testclient import TestClient
client = TestClient(server.app)

# 1) get_db_context_range: estructura + stats (sin Claude, gratis)
print("=== 1) get_db_context_range (sin Claude) ===")
ctx, stats = server.get_db_context_range("Paris", "2026-07-13", "2026-07-15")
print("stats:", json.dumps(stats, ensure_ascii=False))
print("dias en contexto:", ctx.count("=== DAY "))
print("tiene spanning:", "TODO EL RANGO" in ctx)
print("tiene clima por dia:", "CLIMA POR DIA" in ctx)
print("chars de contexto:", len(ctx))

# 2) Validaciones (sin Claude, no cobran)
print("\n=== 2) Validaciones (400, sin cobro) ===")
for params, label in [
    ({"city": "Paris", "query": "x", "date_from": "2026-07-13", "date_to": "2026-07-25"}, "rango >5 dias"),
    ({"city": "Paris", "query": "x", "date_from": "2026-07-15", "date_to": "2026-07-13"}, "to < from"),
    ({"city": "Paris", "query": "x", "date_from": "2026-07-13"}, "solo date_from"),
    ({"city": "Paris", "query": "x", "date_from": "bad", "date_to": "2026-07-15"}, "formato malo"),
]:
    r = client.get("/ask", params=params)
    print(f"  {label}: HTTP {r.status_code} -> {r.json().get('error','')[:60]}")

# 3) UNA consulta real de itinerario (SI llama a Claude, ~$0.04)
print("\n=== 3) Itinerario real 3 dias (1 consulta a Claude) ===")
r = client.get("/ask", params={
    "city": "Paris",
    "query": "itinerario para una pareja que ama arte y buena comida",
    "date_from": "2026-07-13", "date_to": "2026-07-15",
})
print("HTTP", r.status_code)
data = r.json()
print("date_from/to:", data.get("date_from"), data.get("date_to"), "| date:", data.get("date"))
print("research_proof:", json.dumps(data.get("research_proof"), ensure_ascii=False))
ans = data.get("response") or ""
print("dias mencionados en respuesta (13/14/15):",
      sum(d in ans for d in ["13", "14", "15"]))
print("\n--- respuesta (primeros 700) ---\n", ans[:700])
