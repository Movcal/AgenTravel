"""
AgenTravel - Servidor FastAPI con x402 payment middleware.
Cobra 0.10 USDC por consulta via X Layer (OKX).
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse
from datetime import date, timedelta
from dotenv import load_dotenv
import anthropic
import unicodedata

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from db.database import init_db, get_connection

# ──────────────────────────────────────────────
# Configuracion x402
# ──────────────────────────────────────────────
OKX_API_KEY    = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
PAY_TO_ADDRESS = os.getenv("PAY_TO_ADDRESS")
NETWORK        = "eip155:196"   # X Layer Mainnet
PRICE          = "$0.10"

TRAVEL_SYSTEM_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "..", "prompts", "agent_travel.md"),
    encoding="utf-8"
).read()

app = FastAPI(
    title="AgenTravel API",
    description="Agente turistico con recomendaciones personalizadas por ciudad y fecha. Cobra 0.10 USDC via x402 (X Layer).",
    version="1.0.0",
)

# ──────────────────────────────────────────────
# Integracion x402
# ──────────────────────────────────────────────
def setup_x402():
    """Configura el middleware x402 si las keys estan disponibles."""
    if not all([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, PAY_TO_ADDRESS]):
        print("[WARNING] Keys OKX no configuradas. Modo sin pago activo.")
        return

    try:
        from x402.http import (
            OKXAuthConfig,
            OKXFacilitatorClient,
            OKXFacilitatorConfig,
            PaymentOption,
        )
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact.server import ExactEvmScheme
        from x402.server import x402ResourceServer

        facilitator = OKXFacilitatorClient(
            OKXFacilitatorConfig(
                auth=OKXAuthConfig(
                    api_key=OKX_API_KEY,
                    secret_key=OKX_SECRET_KEY,
                    passphrase=OKX_PASSPHRASE,
                ),
                sync_settle=True,
            )
        )

        server = x402ResourceServer(facilitator)
        server.register(NETWORK, ExactEvmScheme())

        routes = {
            "GET /ask": RouteConfig(
                accepts=[
                    PaymentOption(
                        scheme="exact",
                        price=PRICE,
                        network=NETWORK,
                        pay_to=PAY_TO_ADDRESS,
                        max_timeout_seconds=300,
                    ),
                ],
                description="AgenTravel - Recomendaciones turisticas personalizadas por ciudad y fecha",
                mime_type="application/json",
            ),
        }

        app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
        print(f"[x402] Middleware activado. Precio: {PRICE} en {NETWORK} -> {PAY_TO_ADDRESS}")

    except ImportError:
        print("[WARNING] Libreria x402 no instalada. Correr: pip install okxweb3-app-x402")
    except Exception as e:
        print(f"[ERROR] x402 setup failed: {e}")


setup_x402()
init_db()


# ──────────────────────────────────────────────
# Funciones de datos
# ──────────────────────────────────────────────
def normalize_text(s: str) -> str:
    """Quita acentos y pasa a minusculas: 'París' -> 'paris'."""
    return (
        unicodedata.normalize("NFKD", s or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )


def find_city(conn, city: str):
    """Busca la ciudad ignorando acentos y mayusculas ('Paris' encuentra 'París')."""
    target = normalize_text(city)
    if not target:
        return None
    for row in conn.execute("SELECT id, name, country FROM cities").fetchall():
        name = normalize_text(row[1])
        if target in name or name in target:
            return row
    return None


def get_db_context(city: str, target_date: str | None) -> str:
    """Recupera lugares y eventos relevantes de la DB para el agente."""
    conn = get_connection()

    row = find_city(conn, city)

    if not row:
        conn.close()
        return f"No hay datos disponibles para '{city}' en la base de datos."

    city_id, city_name, country = row[0], row[1], row[2]

    today = date.today().isoformat()
    check_date = target_date or today

    # Eventos para esa fecha (o proximos 30 dias si no hay fecha especifica).
    # LIMIT 40: sin limite, ciudades como Paris matchean 700+ eventos por fecha
    # y el costo de Claude por consulta supera lo que se cobra.
    # Se priorizan eventos de corta duracion (conciertos, partidos, funciones)
    # sobre exposiciones que duran meses/anios, que son menos "evento".
    # Solo status scheduled/active: nunca recomendar cancelados ni archivados.
    if target_date:
        events = conn.execute('''
            SELECT name, category, venue, time, price, ticket_source, is_free,
                   start_date, end_date, target_audience, status, official_source
            FROM events
            WHERE city_id=? AND start_date <= ? AND end_date >= ?
              AND status IN ('scheduled', 'active')
            ORDER BY julianday(end_date) - julianday(start_date) ASC,
                     is_free DESC, start_date
            LIMIT 40
        ''', (city_id, check_date, check_date)).fetchall()
    else:
        future_date = (date.today() + timedelta(days=30)).isoformat()
        events = conn.execute('''
            SELECT name, category, venue, time, price, ticket_source, is_free,
                   start_date, end_date, target_audience, status, official_source
            FROM events
            WHERE city_id=? AND end_date >= ? AND start_date <= ?
              AND status IN ('scheduled', 'active')
            ORDER BY julianday(end_date) - julianday(start_date) ASC,
                     is_free DESC, start_date
            LIMIT 40
        ''', (city_id, today, future_date)).fetchall()

    # Lugares permanentes
    places = conn.execute('''
        SELECT name, category, description, opening_hours, closed_days,
               price, address, contact, official_website, is_free, target_audience,
               last_verified
        FROM places WHERE city_id=?
        ORDER BY is_free DESC, name
    ''', (city_id,)).fetchall()
    conn.close()

    context = f"DATOS DE LA BASE DE DATOS - {city_name}, {country}\n"
    context += f"Fecha consultada: {check_date}\n"
    context += f"Hoy: {today}\n\n"

    if events:
        context += f"=== EVENTOS DISPONIBLES ({len(events)} encontrados) ===\n"
        for e in events:
            context += (
                f"\n- {e[0]}\n"
                f"  Categoria: {e[1]} | Lugar: {e[2]}\n"
                f"  Desde: {e[7]} Hasta: {e[8]} | Horario: {e[3]}\n"
                f"  Precio: {e[4]} | Gratuito: {'Si' if e[6] else 'No'}\n"
                f"  Audiencia: {e[9]} | Estado: {e[10]}\n"
                f"  Link: {e[5]}\n"
                f"  Fuente oficial: {e[11] or e[5]}\n"
            )
    else:
        context += "=== SIN EVENTOS ESPECIFICOS PARA ESA FECHA ===\n"
        context += "(Mostrar lugares permanentes disponibles)\n"

    context += f"\n=== LUGARES PERMANENTES ({len(places)} disponibles) ===\n"
    for p in places:
        context += (
            f"\n- {p[0]}\n"
            f"  Categoria: {p[1]}\n"
            f"  Horarios: {p[3]} | Cerrado: {p[4]}\n"
            f"  Precio: {p[5]} | Gratuito: {'Si' if p[9] else 'No'}\n"
            f"  Direccion: {p[6]}\n"
            f"  Web oficial: {p[8]} | Verificado: {p[11]}\n"
            f"  Descripcion: {(p[2] or '')}\n"
        )

    return context


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service":     "AgenTravel API",
        "version":     "1.0.0",
        "description": "Agente turistico con recomendaciones personalizadas",
        "endpoints": {
            "GET /ask":    "Consulta de viaje (0.10 USDC via x402)",
            "GET /health": "Estado del servicio",
            "GET /cities": "Ciudades disponibles",
        },
        "payment": {
            "protocol": "x402",
            "price":    PRICE,
            "network":  NETWORK,
            "pay_to":   PAY_TO_ADDRESS,
        }
    }


@app.get("/health")
def health():
    conn = get_connection()
    cities = conn.execute("SELECT name, country FROM cities").fetchall()
    stats = []
    for c in cities:
        city_id = conn.execute(
            "SELECT id FROM cities WHERE name=?", (c[0],)
        ).fetchone()[0]
        places = conn.execute(
            "SELECT COUNT(*) FROM places WHERE city_id=?", (city_id,)
        ).fetchone()[0]
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE city_id=? AND end_date >= ?",
            (city_id, date.today().isoformat())
        ).fetchone()[0]
        stats.append({"city": c[0], "country": c[1], "places": places, "upcoming_events": events})

    return {"status": "ok", "cities": stats}


@app.get("/cities")
def cities():
    conn = get_connection()
    rows = conn.execute("SELECT name, country FROM cities ORDER BY name").fetchall()
    return {"cities": [{"name": r[0], "country": r[1]} for r in rows]}


@app.get("/ask")
async def ask(
    request:  Request,
    city:     str   = Query(...,  description="Ciudad a consultar (ej: Buenos Aires, Santiago de Chile)"),
    query:    str   = Query(...,  description="Pregunta del viajero en lenguaje natural"),
    date:     str | None = Query(None, description="Fecha en formato YYYY-MM-DD (opcional)"),
):
    """
    Consulta al agente de viajes. Costo: 0.10 USDC via x402 (X Layer).

    Ejemplos:
    - /ask?city=Santiago de Chile&query=que puedo hacer mañana con presupuesto limitado&date=2026-07-25
    - /ask?city=Buenos Aires&query=planes para el fin de semana con niños&date=2026-07-18
    """
    # Obtener contexto de la DB
    context = get_db_context(city, date)

    # Llamar al modelo
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_message = f"{context}\n\nPREGUNTA DEL VIAJERO: {query}"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=TRAVEL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer = response.content[0].text

        return JSONResponse({
            "city":        city,
            "date":        date,
            "query":       query,
            "response":    answer,
            "data_source": "AgenTravel DB + Claude Sonnet 4.6",
        })

    except Exception as e:
        return JSONResponse(
            {"error": str(e), "city": city, "date": date},
            status_code=500
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4021, reload=False)
