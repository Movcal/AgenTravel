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

from db.database import init_db, get_connection, get_meta

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


def _domain(url: str | None) -> str | None:
    """Extrae el dominio de una URL para contar fuentes distintas.
    'https://www.teatrocolon.org.ar/es/agenda' -> 'teatrocolon.org.ar'."""
    if not url or not isinstance(url, str):
        return None
    m = re.search(r"https?://([^/]+)", url.strip())
    if not m:
        return None
    host = m.group(1).lower()
    return host[4:] if host.startswith("www.") else host


def get_db_context(city: str, target_date: str | None):
    """Recupera lugares y eventos relevantes de la DB para el agente.
    Devuelve (context_str, stats_dict). stats_dict alimenta el
    'research_proof' deterministico que se agrega a la respuesta de /ask."""
    empty_stats = {
        "events_verified": 0, "permanent_exhibitions": 0,
        "places_verified": 0, "official_sources": 0, "weather": None,
    }
    conn = get_connection()

    row = find_city(conn, city)

    if not row:
        conn.close()
        return f"No hay datos disponibles para '{city}' en la base de datos.", empty_stats

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

    weather_ctx = get_weather_context(city_name, target_date)
    context += weather_ctx

    # Fuentes oficiales distintas que respaldan lo que entra al contexto:
    # eventos (official_source o su link), exposiciones y webs de lugares.
    sources = set()
    for e in events:
        d = _domain(e[11]) or _domain(e[5])   # official_source o Link
        if d:
            sources.add(d)
    for e in long_events:
        d = _domain(e[6])                      # ticket_source/link
        if d:
            sources.add(d)
    for p in places:
        d = _domain(p[8])                      # official_website
        if d:
            sources.add(d)

    stats = {
        "events_verified":       len(events),
        "permanent_exhibitions": len(long_events),
        "places_verified":       len(places),
        "official_sources":      len(sources),
        # Solo cuenta como "en vivo" el pronostico real, no la nota de >16 dias.
        "weather": "Open-Meteo (live)" if "(fuente: Open-Meteo)" in weather_ctx else None,
    }

    return context, stats


def get_weather_range(city_name: str, date_from: str, date_to: str) -> str:
    """Pronostico dia por dia para un rango, en UNA sola llamada a Open-Meteo.
    Solo pide dias dentro del horizonte de 16 dias; los posteriores llevan
    una nota de 'no inventar'. Nunca rompe la consulta."""
    coords = CITY_COORDS.get(normalize_text(city_name))
    if not coords:
        return ""
    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        d_to   = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return ""
    today   = date.today()
    horizon = today + timedelta(days=15)
    api_from = max(d_from, today)
    api_to   = min(d_to, horizon)

    lines = []
    if api_from <= api_to:
        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": coords[0], "longitude": coords[1],
                    "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "start_date": api_from.isoformat(), "end_date": api_to.isoformat(),
                },
                timeout=8,
            )
            resp.raise_for_status()
            d = resp.json()["daily"]
            for i, day in enumerate(d["time"]):
                desc = WMO_CODES.get(d["weathercode"][i], "Sin descripcion")
                prob = d["precipitation_probability_max"][i]
                lluvia = f"{prob}%" if prob is not None else "sin dato"
                lines.append(
                    f"{day}: {desc}. {d['temperature_2m_min'][i]}C a "
                    f"{d['temperature_2m_max'][i]}C. Lluvia: {lluvia}."
                )
        except Exception:
            lines = []

    note = ""
    if d_to > horizon:
        note = (
            f"Los dias posteriores a {horizon.isoformat()} estan fuera del horizonte "
            "de pronostico (16 dias): no inventar clima para esos dias.\n"
        )
    if not lines and not note:
        return ""
    out = "\n=== PRONOSTICO DEL CLIMA POR DIA (fuente: Open-Meteo) ===\n"
    if lines:
        out += "\n".join(lines) + "\n"
    out += note
    out += "Usar el clima de cada dia para distribuir actividades (aire libre vs bajo techo).\n"
    return out


def get_db_context_range(city: str, date_from: str, date_to: str):
    """Contexto para itinerario multi-dia. Devuelve (context_str, stats_dict).
    Estructura: eventos que cubren todo el rango una sola vez (spanning),
    luego un bloque por dia (=== DAY ... ===) con eventos especificos de esa
    fecha, exposiciones largas y lugares una sola vez."""
    empty_stats = {
        "events_verified": 0, "permanent_exhibitions": 0,
        "places_verified": 0, "official_sources": 0, "weather": None,
    }
    conn = get_connection()
    row = find_city(conn, city)
    if not row:
        conn.close()
        return f"No hay datos disponibles para '{city}' en la base de datos.", empty_stats
    city_id, city_name, country = row[0], row[1], row[2]

    today = date.today().isoformat()
    d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
    d_to   = datetime.strptime(date_to, "%Y-%m-%d").date()
    days = []
    d = d_from
    while d <= d_to:
        days.append(d.isoformat())
        d += timedelta(days=1)

    status_ok = "status IN ('scheduled', 'active')"
    short = "julianday(end_date) - julianday(start_date) <= 366"

    # Spanning: eventos <= 1 anio que cubren TODO el rango (disponibles cualquier
    # dia). Se listan una sola vez para no repetirlos en cada dia.
    spanning = conn.execute(f'''
        SELECT id, name, category, venue, time, price, ticket_source, is_free,
               start_date, end_date, target_audience, official_source
        FROM events
        WHERE city_id=? AND start_date <= ? AND end_date >= ? AND {status_ok}
          AND {short}
        ORDER BY is_free DESC, name
        LIMIT 15
    ''', (city_id, date_from, date_to)).fetchall()

    # Eventos especificos por dia: solapan ese dia, duran <= 1 anio y NO cubren
    # todo el rango (esos ya estan en spanning). LIMIT 12/dia controla tokens.
    per_day = {}
    for day in days:
        per_day[day] = conn.execute(f'''
            SELECT id, name, category, venue, time, price, ticket_source, is_free,
                   start_date, end_date, target_audience, official_source
            FROM events
            WHERE city_id=? AND start_date <= ? AND end_date >= ? AND {status_ok}
              AND {short}
              AND NOT (start_date <= ? AND end_date >= ?)
            ORDER BY julianday(end_date) - julianday(start_date) ASC,
                     is_free DESC, start_date
            LIMIT 12
        ''', (city_id, day, day, date_from, date_to)).fetchall()

    # Exposiciones de larga duracion (> 1 anio) que tocan el rango: una vez.
    long_events = conn.execute(f'''
        SELECT name, category, venue, price, is_free, end_date, ticket_source
        FROM events
        WHERE city_id=? AND start_date <= ? AND end_date >= ? AND {status_ok}
          AND julianday(end_date) - julianday(start_date) > 366
        ORDER BY is_free DESC, end_date
        LIMIT 10
    ''', (city_id, date_to, date_from)).fetchall()

    places = conn.execute('''
        SELECT name, category, description, opening_hours, closed_days,
               price, address, contact, official_website, is_free, target_audience,
               last_verified
        FROM places WHERE city_id=?
        ORDER BY is_free DESC, name
    ''', (city_id,)).fetchall()
    conn.close()

    context = f"DATOS DE LA BASE DE DATOS - {city_name}, {country}\n"
    context += f"Rango consultado: {date_from} a {date_to} ({len(days)} dias)\n"
    context += f"Hoy: {today}\n\n"

    if spanning:
        context += f"=== EVENTOS DISPONIBLES TODO EL RANGO ({len(spanning)}) ===\n"
        context += "(Disponibles cualquier dia del viaje; repartilos, no los repitas todos los dias)\n"
        for e in spanning:
            context += (
                f"\n- {e[1]}\n"
                f"  Categoria: {e[2]} | Lugar: {e[3]}\n"
                f"  Desde: {e[8]} Hasta: {e[9]} | Horario: {e[4]}\n"
                f"  Precio: {e[5]} | Gratuito: {'Si' if e[7] else 'No'}\n"
                f"  Audiencia: {e[10]}\n"
                f"  Link: {e[6]}\n"
                f"  Fuente oficial: {e[11] or e[6]}\n"
            )

    for day in days:
        evs = per_day[day]
        context += f"\n=== DAY {day} ({len(evs)} eventos especificos) ===\n"
        if not evs:
            context += "(Sin eventos especificos ese dia; usar spanning + lugares permanentes)\n"
        for e in evs:
            context += (
                f"- {e[1]} | {e[2]} | {e[3]} | {e[8]}-{e[9]} | Horario: {e[4]} | "
                f"Precio: {e[5]}{' | Gratuito' if e[7] else ''} | Link: {e[6]}\n"
            )

    if long_events:
        context += f"\n=== EXPOSICIONES Y ACTIVIDADES DE LARGA DURACION ({len(long_events)}) ===\n"
        for e in long_events:
            context += (
                f"- {e[0]} | {e[1]} | {e[2]} | Precio: {e[3]}"
                f"{' | Gratuito' if e[4] else ''} | Hasta: {e[5]} | Link: {e[6]}\n"
            )

    context += f"\n=== LUGARES PERMANENTES ({len(places)} disponibles) ===\n"
    context += "(Distribuir entre los dias; NO repetir un lugar en dos dias distintos)\n"
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

    weather_ctx = get_weather_range(city_name, date_from, date_to)
    context += weather_ctx

    # Stats para research_proof: eventos cortos DISTINTOS (spanning + por dia),
    # exposiciones largas, lugares y dominios oficiales distintos de todo el rango.
    short_ids = {e[0] for e in spanning}
    for day in days:
        short_ids.update(e[0] for e in per_day[day])

    sources = set()
    for e in spanning:
        dm = _domain(e[11]) or _domain(e[6])
        if dm:
            sources.add(dm)
    for day in days:
        for e in per_day[day]:
            dm = _domain(e[11]) or _domain(e[6])
            if dm:
                sources.add(dm)
    for e in long_events:
        dm = _domain(e[6])
        if dm:
            sources.add(dm)
    for p in places:
        dm = _domain(p[8])
        if dm:
            sources.add(dm)

    stats = {
        "events_verified":       len(short_ids),
        "permanent_exhibitions": len(long_events),
        "places_verified":       len(places),
        "official_sources":      len(sources),
        "weather": "Open-Meteo (live)" if "(fuente: Open-Meteo)" in weather_ctx else None,
    }
    return context, stats


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


# Itinerario multi-dia: tope de dias para que un rango largo no funda el
# margen (mas dias = mas tokens de contexto que el ingreso fijo de $0.10).
MAX_ITINERARY_DAYS = 5


@app.get("/ask")
async def ask(
    request:   Request,
    city:      str   = Query(...,  description="Ciudad a consultar (ej: Buenos Aires, Santiago de Chile)"),
    query:     str   = Query(...,  description="Pregunta del viajero en lenguaje natural"),
    date:      str | None = Query(None, description="Fecha unica YYYY-MM-DD (opcional)"),
    date_from: str | None = Query(None, description="Inicio del rango YYYY-MM-DD para itinerario multi-dia (opcional)"),
    date_to:   str | None = Query(None, description="Fin del rango YYYY-MM-DD (opcional; max 5 dias, requiere date_from)"),
):
    """
    Consulta al agente de viajes. Costo: 0.10 USDC via x402 (X Layer).

    Modo dia unico:
    - /ask?city=Santiago de Chile&query=que hacer con presupuesto limitado&date=2026-07-25

    Modo itinerario (rango, max 5 dias): pasar date_from y date_to (ignora date).
    - /ask?city=Paris&query=itinerario para una pareja&date_from=2026-07-20&date_to=2026-07-23
    """
    # Modo rango: si viene date_from o date_to, se arma un itinerario y se
    # ignora `date`. Se validan ANTES de cobrar (el pago no se liquida en >=400).
    is_range = bool(date_from or date_to)
    if is_range:
        if not (date_from and date_to):
            return JSONResponse(
                {"error": "Provide both date_from and date_to for an itinerary (YYYY-MM-DD). You were not charged for this request."},
                status_code=400,
            )
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            d_to   = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse(
                {"error": "Invalid date_from/date_to. Use YYYY-MM-DD (e.g. 2026-07-20). You were not charged for this request."},
                status_code=400,
            )
        if d_to < d_from:
            return JSONResponse(
                {"error": "date_to must be on or after date_from. You were not charged for this request."},
                status_code=400,
            )
        n_days = (d_to - d_from).days + 1
        if n_days > MAX_ITINERARY_DAYS:
            return JSONResponse(
                {"error": f"Itinerary range too long: {n_days} days. Maximum is {MAX_ITINERARY_DAYS} days. You were not charged for this request."},
                status_code=400,
            )
    elif date is not None:
        # Validar fecha unica: un date malformado compararia strings en silencio.
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return JSONResponse(
                {"error": f"Invalid date: '{date}'. Use YYYY-MM-DD format (e.g. 2026-07-15). You were not charged for this request."},
                status_code=400,
            )

    # Validar ciudad antes de procesar: el middleware x402 NO liquida el pago
    # en respuestas >= 400, asi que un 404 aca significa que el cliente no
    # paga por una ciudad sin cobertura (y nosotros no llamamos a Claude).
    conn = get_connection()
    row = find_city(conn, city)
    if not row:
        available = [r[0] for r in conn.execute(
            "SELECT name FROM cities ORDER BY name"
        ).fetchall()]
        conn.close()
        return JSONResponse(
            {
                "error": f"City not available: '{city}'. You were not charged for this request.",
                "available_cities": available,
                "hint": "Check coverage for free at GET /cities before paying.",
            },
            status_code=404,
        )
    conn.close()

    # Obtener contexto de la DB (+ stats deterministicos para el comprobante).
    # El itinerario trae mas contexto -> mas tokens de salida permitidos.
    if is_range:
        context, stats = get_db_context_range(city, date_from, date_to)
        max_tokens = 3500
    else:
        context, stats = get_db_context(city, date)
        max_tokens = 2048

    # Llamar al modelo
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_message = f"{context}\n\nPREGUNTA DEL VIAJERO: {query}"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=TRAVEL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer = response.content[0].text

        # Comprobante de investigacion: metadata verificable, calculada por
        # nosotros (no por Claude). Es el diferenciador visible vs un chat
        # generico: cuantos eventos/lugares reales y de cuantas fuentes
        # oficiales sale la respuesta, mas cuando se refresco la data.
        research_proof = {
            "events_verified":       stats["events_verified"],
            "permanent_exhibitions": stats["permanent_exhibitions"],
            "places_verified":       stats["places_verified"],
            "official_sources":      stats["official_sources"],
            "weather":               stats["weather"],
            "coverage_note": (
                "Built from AgenTravel's verified events database, "
                "cross-checked against official sources with source links included."
            ),
        }
        last_refresh = get_meta("last_guardian_run")
        if last_refresh:
            research_proof["last_data_refresh"] = last_refresh

        return JSONResponse({
            "city":           city,
            "date":           None if is_range else date,
            "date_from":      date_from if is_range else None,
            "date_to":        date_to if is_range else None,
            "query":          query,
            "response":       answer,
            "research_proof": research_proof,
            "data_source":    "AgenTravel DB + Claude Sonnet 4.6",
        })

    except Exception as e:
        return JSONResponse(
            {"error": str(e), "city": city, "date": date,
             "date_from": date_from, "date_to": date_to},
            status_code=500
        )


# ──────────────────────────────────────────────
# Guardian embebido (scheduler en el mismo proceso)
# ──────────────────────────────────────────────
def _guardian_loop(hour: int):
    """Corre el Guardian una vez al dia dentro del proceso del API.
    Va en el MISMO proceso a proposito: asi escribe en el mismo archivo
    SQLite que lee el API (dos servicios de Railway no comparten disco)."""
    import time
    from datetime import datetime as _dt, timedelta as _td
    from agents.guardian import run_guardian

    # Corrida inicial liviana al arrancar: archiva eventos ya vencidos
    # (sin refrescar importers) para que /ask no muestre nada pasado.
    try:
        print("[Guardian-thread] Corrida inicial (solo archivar)...")
        run_guardian(refresh=False)
    except Exception as e:
        print(f"[Guardian-thread] Error en corrida inicial: {e}")

    while True:
        now = _dt.now()
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now >= nxt:
            nxt += _td(days=1)
        wait = (nxt - now).total_seconds()
        print(f"[Guardian-thread] Proxima corrida completa: {nxt:%Y-%m-%d %H:%M}")
        time.sleep(wait)
        try:
            run_guardian(refresh=True)   # refresca importers + archiva
        except Exception as e:
            print(f"[Guardian-thread] Error: {e}")
        time.sleep(60)  # no re-disparar en el mismo minuto


def start_guardian_thread():
    """Arranca el Guardian en un hilo daemon si esta habilitado."""
    if os.getenv("GUARDIAN_ENABLED", "1") == "0":
        print("[Guardian-thread] Deshabilitado (GUARDIAN_ENABLED=0).")
        return
    import threading
    hour = int(os.getenv("GUARDIAN_HOUR", "3"))
    t = threading.Thread(target=_guardian_loop, args=(hour,), daemon=True)
    t.start()
    print(f"[Guardian-thread] Activo. Refresco diario a las {hour:02d}:00.")


if __name__ == "__main__":
    import uvicorn
    # El scheduler arranca solo aca (no al importar en tests): en Railway el
    # startCommand es 'python api/server.py', asi que entra por este bloque.
    start_guardian_thread()
    # Railway (y cualquier PaaS) inyecta el puerto en $PORT. En local usa 4021.
    port = int(os.getenv("PORT", "4021"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
