"""
AgenTravel - Servidor FastAPI con x402 payment middleware.
Cobra 0.10 USDC por consulta via X Layer (OKX).
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
import anthropic
import unicodedata
import re
import requests

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from db.database import init_db, get_connection

# ──────────────────────────────────────────────
# Configuracion x402
# ──────────────────────────────────────────────
OKX_API_KEY    = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
PAY_TO_ADDRESS = os.getenv("PAY_TO_ADDRESS")
# X Layer: mainnet = eip155:196, testnet = eip155:1952
# Se controla desde .env (X402_NETWORK) para probar sin plata real.
NETWORK        = os.getenv("X402_NETWORK", "eip155:196")
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

        # El paquete Python (0.1.1) no trae la config de X Layer testnet;
        # los SDKs oficiales de Go/TS si. Se agrega el mismo asset que usan
        # ellos (USDT0 testnet) para que el precio "$0.10" se pueda convertir.
        from x402.mechanisms.evm.constants import NETWORK_CONFIGS
        NETWORK_CONFIGS.setdefault("eip155:1952", {
            "chain_id": 1952,
            "default_asset": {
                "address": "0x9e29b3aada05bf2d2c827af80bd28dc0b9b4fb0c",
                "name": "USD₮0",
                "version": "1",
                "decimals": 6,
            },
        })

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
        # Sin initialize() toda request paga muere en 500 "Failed to process
        # request": el server necesita consultar al facilitador que redes y
        # esquemas soporta. Tambien valida las keys OKX al arrancar.
        server.initialize()

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


# Coordenadas para el pronostico del clima (Open-Meteo, gratis y sin API key)
CITY_COORDS = {
    "buenos aires":      (-34.6037, -58.3816),
    "santiago de chile": (-33.4489, -70.6693),
    "rio de janeiro":    (-22.9068, -43.1729),
    "madrid":            (40.4168, -3.7038),
    "paris":             (48.8566, 2.3522),
    "new york city":     (40.7128, -74.0060),
}

WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Niebla", 48: "Niebla con escarcha",
    51: "Llovizna ligera", 53: "Llovizna", 55: "Llovizna intensa",
    61: "Lluvia ligera", 63: "Lluvia", 65: "Lluvia fuerte",
    71: "Nieve ligera", 73: "Nieve", 75: "Nieve fuerte",
    80: "Chubascos ligeros", 81: "Chubascos", 82: "Chubascos fuertes",
    95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta con granizo fuerte",
}


def get_weather_context(city_name: str, target_date: str | None) -> str:
    """Pronostico del dia consultado via Open-Meteo. Nunca rompe la consulta:
    si falla o la fecha esta fuera del horizonte de pronostico, devuelve
    una nota o string vacio y el agente responde sin clima."""
    coords = CITY_COORDS.get(normalize_text(city_name))
    if not coords:
        return ""
    check = target_date or date.today().isoformat()
    try:
        days_ahead = (datetime.strptime(check, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return ""
    if days_ahead < 0:
        return ""  # fecha pasada: no aplica pronostico
    if days_ahead > 15:
        return (
            "\n=== PRONOSTICO DEL CLIMA ===\n"
            f"La fecha {check} esta a mas de 16 dias: todavia no existe pronostico "
            "confiable. No inventar clima; sugerir segun la estacion del anio.\n"
        )
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": coords[0], "longitude": coords[1],
                "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto", "start_date": check, "end_date": check,
            },
            timeout=8,
        )
        resp.raise_for_status()
        d = resp.json()["daily"]
        desc = WMO_CODES.get(d["weathercode"][0], "Sin descripcion")
        prob = d["precipitation_probability_max"][0]
        lluvia = f"{prob}%" if prob is not None else "sin dato"
        return (
            "\n=== PRONOSTICO DEL CLIMA (fuente: Open-Meteo) ===\n"
            f"{check}: {desc}. Temperatura: {d['temperature_2m_min'][0]}C a "
            f"{d['temperature_2m_max'][0]}C. Probabilidad de lluvia: {lluvia}.\n"
            "Usar para elegir entre actividades al aire libre o bajo techo.\n"
        )
    except Exception:
        return ""


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

    # Ventana de fechas: la fecha exacta consultada, o los proximos 30 dias.
    if target_date:
        range_start = range_end = check_date
    else:
        range_start = today
        range_end   = (date.today() + timedelta(days=30)).isoformat()

    # Eventos "reales" (duracion <= 1 anio): conciertos, partidos, funciones.
    # LIMIT 40: sin limite, ciudades como Paris matchean 700+ eventos por fecha
    # y el costo de Claude por consulta supera lo que se cobra.
    # Solo status scheduled/active: nunca recomendar cancelados ni archivados.
    base_where = '''city_id=? AND start_date <= ? AND end_date >= ?
              AND status IN ('scheduled', 'active')'''
    params = (city_id, range_end, range_start)

    events = conn.execute(f'''
        SELECT name, category, venue, time, price, ticket_source, is_free,
               start_date, end_date, target_audience, status, official_source
        FROM events
        WHERE {base_where}
          AND julianday(end_date) - julianday(start_date) <= 366
        ORDER BY julianday(end_date) - julianday(start_date) ASC,
                 is_free DESC, start_date
        LIMIT 40
    ''', params).fetchall()

    # Exposiciones/actividades que duran mas de un anio: son casi "lugares".
    # Van en seccion aparte y compacta para no inflar el contexto.
    long_events = conn.execute(f'''
        SELECT name, category, venue, price, is_free, end_date, ticket_source
        FROM events
        WHERE {base_where}
          AND julianday(end_date) - julianday(start_date) > 366
        ORDER BY is_free DESC, end_date
        LIMIT 10
    ''', params).fetchall()

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

    if long_events:
        context += f"\n=== EXPOSICIONES Y ACTIVIDADES DE LARGA DURACION ({len(long_events)}) ===\n"
        for e in long_events:
            context += (
                f"- {e[0]} | {e[1]} | {e[2]} | Precio: {e[3]}"
                f"{' | Gratuito' if e[4] else ''} | Hasta: {e[5]} | Link: {e[6]}\n"
            )

    context += f"\n=== LUGARES PERMANENTES ({len(places)} disponibles) ===\n"
    for p in places:
        context += (
            f"\n- {p[0]}\n"
            f"  Categoria: {p[1]}\n"
            f"  Horarios: {p[3]} | Cerrado: {p[4]}\n"
            f"  Precio: {p[5]} | Gratuito: {'Si' if p[9] else 'No'}\n"
            f"  Direccion: {p[6]}\n"
            f"  Web oficial: {p[8]} | Verificado: {p[11]}\n"
            f"  Descripcion: {(p[2] or '')[:220]}\n"
        )

    context += get_weather_context(city_name, target_date)

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
            "GET /stats":  "Estadisticas de eventos por ciudad/mes, incluye historial archivado",
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
    today = date.today().isoformat()
    rows = conn.execute('''
        SELECT c.name, c.country,
               (SELECT COUNT(*) FROM places p WHERE p.city_id = c.id) AS places,
               (SELECT COUNT(*) FROM events e
                 WHERE e.city_id = c.id AND e.end_date >= ?
                   AND e.status IN ('scheduled','active')) AS upcoming
        FROM cities c ORDER BY c.name
    ''', (today,)).fetchall()
    conn.close()
    return {"status": "ok", "cities": [
        {"city": r[0], "country": r[1], "places": r[2], "upcoming_events": r[3]}
        for r in rows
    ]}


@app.get("/cities")
def cities():
    conn = get_connection()
    rows = conn.execute("SELECT name, country FROM cities ORDER BY name").fetchall()
    conn.close()
    return {"cities": [{"name": r[0], "country": r[1]} for r in rows]}


@app.get("/stats")
def stats(
    city:  str        = Query(...,  description="Ciudad a consultar (acepta sin acentos)"),
    month: str | None = Query(None, description="Mes: '03', '3' o '2026-03'. Sin mes = todo el historial"),
):
    """
    Estadisticas de eventos, incluyendo el archivo historico.
    AgenTravel preserva los eventos pasados: esto responde preguntas como
    'que venue tiene los mejores eventos en marzo' que un chat no puede responder.

    Ejemplos:
    - /stats?city=Buenos Aires&month=03      -> todos los marzos registrados
    - /stats?city=Paris&month=2026-08        -> agosto 2026 especifico
    - /stats?city=Madrid                     -> historial completo
    """
    conn = get_connection()
    row = find_city(conn, city)
    if not row:
        conn.close()
        return JSONResponse({"error": f"No hay datos para '{city}'"}, status_code=404)
    city_id, city_name, country = row[0], row[1], row[2]

    where  = "city_id=?"
    params = [city_id]
    period = "todo el historial"
    if month:
        m = month.strip()
        if re.fullmatch(r"\d{4}-\d{2}", m):
            where += " AND substr(start_date,1,7) = ?"
            params.append(m)
            period = m
        elif re.fullmatch(r"\d{1,2}", m) and 1 <= int(m) <= 12:
            mm = f"{int(m):02d}"
            where += " AND substr(start_date,6,2) = ?"
            params.append(mm)
            period = f"mes {mm} (todos los años registrados)"
        else:
            conn.close()
            return JSONResponse(
                {"error": f"Mes invalido: '{month}'. Usar '03', '3' o '2026-03'."},
                status_code=400,
            )

    total, free = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(is_free),0) FROM events WHERE {where}", params
    ).fetchone()
    by_category = [
        {"category": r[0] or "Sin categoria", "events": r[1]}
        for r in conn.execute(
            f"SELECT category, COUNT(*) n FROM events WHERE {where} "
            "GROUP BY category ORDER BY n DESC LIMIT 12", params)
    ]
    top_venues = [
        {"venue": r[0] or "Sin venue", "events": r[1]}
        for r in conn.execute(
            f"SELECT venue, COUNT(*) n FROM events WHERE {where} "
            "GROUP BY venue ORDER BY n DESC LIMIT 10", params)
    ]
    by_month = [
        {"month": r[0], "events": r[1]}
        for r in conn.execute(
            f"SELECT substr(start_date,6,2) m, COUNT(*) n FROM events WHERE {where} "
            "GROUP BY m ORDER BY m", params)
    ]
    rng = conn.execute(
        f"SELECT MIN(start_date), MAX(start_date) FROM events WHERE {where}", params
    ).fetchone()
    conn.close()

    return {
        "city":            city_name,
        "country":         country,
        "period":          period,
        "data_range":      {"from": rng[0], "to": rng[1]},
        "total_events":    total,
        "free_events":     free,
        "by_category":     by_category,
        "top_venues":      top_venues,
        "events_by_month": by_month,
        "note": "Incluye eventos historicos archivados: AgenTravel preserva el pasado para analisis de estacionalidad.",
    }


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
    # Validar fecha antes de cobrar trabajo: un date malformado compararia
    # strings en silencio y devolveria resultados incorrectos.
    if date is not None:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return JSONResponse(
                {"error": f"Fecha invalida: '{date}'. Usar formato YYYY-MM-DD (ej: 2026-07-15)."},
                status_code=400,
            )

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
    # Railway (y cualquier PaaS) inyecta el puerto en $PORT. En local usa 4021.
    port = int(os.getenv("PORT", "4021"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
