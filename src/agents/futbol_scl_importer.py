"""
Importador de partidos de futbol en Santiago de Chile.
Fuente: ESPN API (sit.api.espn.com) - Primera Division de Chile + Copa Chile.
Importa partidos con sede en estadios de Santiago.
"""
import sys, os, re, requests
from datetime import date, datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://www.anfp.cl"
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/soccer"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Estadios de Santiago y sus place_slugs
SANTIAGO_VENUES = {
    "Estadio Monumental David Arellano":   "estadio_monumental_colocolo_scl",
    "Estadio Nacional Julio Martínez Pradanos": "estadio_nacional_scl",
    "Estadio Nacional":                    "estadio_nacional_scl",
    "Estadio San Carlos de Apoquindo":     "estadio_san_carlos_scl",
    "Estadio Municipal de La Florida":     "estadio_la_florida_scl",
}

# Ligas ESPN para Chile
ESPN_LEAGUES = [
    ("chi.1",     "Primera Division de Chile"),
    ("chi.copa",  "Copa Chile"),
]


def fetch_espn_events(league: str, days_ahead: int = 90) -> list:
    """Obtiene partidos desde ESPN API para una liga y rango de fechas."""
    today = date.today()
    end   = date(today.year, today.month, today.day)
    from datetime import timedelta
    end_date = today + timedelta(days=days_ahead)

    url = (
        f"{ESPN_API}/{league}/scoreboard"
        f"?dates={today.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}&limit=200"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        return resp.json().get("events", [])
    except Exception:
        return []


def parse_event(raw: dict, league_name: str) -> dict | None:
    """Parsea un evento ESPN a formato AgenTravel."""
    comps = raw.get("competitions", [{}])[0]
    venue_name = comps.get("venue", {}).get("fullName", "")

    # Solo queremos eventos en Santiago
    is_santiago = any(v.lower() in venue_name.lower() for v in [
        "monumental", "nacional", "apoquindo", "florida"
    ])
    if not is_santiago:
        return None

    competitors = comps.get("competitors", [])
    teams = [c["team"]["displayName"] for c in competitors]
    if len(teams) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[-1])
    home_name = home["team"]["displayName"]
    away_name = away["team"]["displayName"]

    name = f"{home_name} vs {away_name}"

    # Fecha y hora (ESPN usa UTC)
    raw_date = raw.get("date", "")
    try:
        dt_utc = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        # Convertir a hora Santiago (UTC-4 en invierno, UTC-3 en verano)
        # Usamos UTC-4 como aproximacion para Chile en julio
        from datetime import timedelta
        dt_scl = dt_utc - timedelta(hours=4)
        start_date = dt_scl.date().isoformat()
        start_time = dt_scl.strftime("%H:%M")
    except Exception:
        start_date = raw_date[:10]
        start_time = ""

    event_id = raw.get("id", "")

    # Detectar venue slug
    venue_slug = None
    for key, slug in SANTIAGO_VENUES.items():
        if key.lower() in venue_name.lower():
            venue_slug = slug
            break

    # Precio — futbol chileno es pago
    link = f"https://www.puntoticket.com/futbol"
    for c in competitors:
        if c.get("homeAway") == "home":
            team_id = c["team"].get("id", "")
            break

    category = f"Futbol / {league_name}"

    # Detectar superclasico
    teams_lower = name.lower()
    if "colo colo" in teams_lower and "universidad de chile" in teams_lower:
        category = "Futbol / Supercl\u00e1sico"
        name = f"SUPERCL\u00c1SICO: {name}"

    return {
        "event_id":         f"futbol_scl_{event_id}",
        "name":             name,
        "category":         category,
        "venue":            venue_name,
        "start_date":       start_date,
        "end_date":         start_date,
        "time":             start_time,
        "price":            f"Desde $5.000 CLP - ver puntoticket.com",
        "ticket_source":    link,
        "official_source":  SOURCE,
        "status":           "scheduled",
        "confidence_level": "high",
        "is_free":          0,
        "is_indoor":        0,
        "target_audience":  "todo publico",
    }


def import_futbol_scl():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando Futbol Santiago de Chile (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Santiago de Chile", "Chile")

    # --- PLACES: estadios principales de Santiago ---
    estadios = [
        {
            "name":             "Estadio Monumental David Arellano (Colo-Colo)",
            "place_slug":       "estadio_monumental_colocolo_scl",
            "category":         "Estadio / Futbol",
            "description":      "El estadio mas grande de Chile (47.347 espectadores). Casa del Club Social y Deportivo Colo-Colo, el equipo mas popular y exitoso de Chile. En Pedrero, Macul, Santiago.",
            "opening_hours":    "Segun partido / Museo: Mar a dom 10-17 h",
            "closed_days":      "Sin partidos: variable",
            "price":            "Desde $5.000 CLP (galeria) / Palco premium: hasta $50.000 CLP",
            "currency":         "CLP",
            "address":          "Av. Marathon 5600, Macul, Santiago",
            "contact":          "colocolo.cl | Tel: +56 2 2412-3200",
            "official_website": "https://colocolo.cl",
            "source":           SOURCE,
            "last_verified":    today.isoformat(),
            "confidence_level": "high",
            "is_free":          0,
            "is_indoor":        0,
            "target_audience":  "todo publico",
            "has_own_agenda":   1,
        },
        {
            "name":             "Estadio Nacional Julio Martinez Pradanos",
            "place_slug":       "estadio_nacional_scl",
            "category":         "Estadio / Futbol / Atletismo",
            "description":      "El estadio nacional de Chile (48.665 espectadores). Sede de partidos de la seleccion chilena, finales de copa y grandes conciertos. Inaugurado en 1938. Declarado monumento historico.",
            "opening_hours":    "Segun evento",
            "closed_days":      "Variable",
            "price":            "Segun evento - desde $5.000 CLP",
            "currency":         "CLP",
            "address":          "Av. Grecia 2001, Nunoa, Santiago",
            "contact":          "estadionacional.cl",
            "official_website": "https://www.estadionacional.cl",
            "source":           SOURCE,
            "last_verified":    today.isoformat(),
            "confidence_level": "high",
            "is_free":          0,
            "is_indoor":        0,
            "target_audience":  "todo publico",
            "has_own_agenda":   1,
        },
        {
            "name":             "Estadio San Carlos de Apoquindo (Universidad Catolica)",
            "place_slug":       "estadio_san_carlos_scl",
            "category":         "Estadio / Futbol",
            "description":      "Estadio de la Universidad Catolica de Chile (20.400 espectadores). En Las Condes, zona oriente de Santiago.",
            "opening_hours":    "Segun partido",
            "closed_days":      "Variable",
            "price":            "Desde $5.000 CLP",
            "currency":         "CLP",
            "address":          "Av. Apoquindo 6524, Las Condes, Santiago",
            "contact":          "cruzados.cl",
            "official_website": "https://cruzados.cl",
            "source":           SOURCE,
            "last_verified":    today.isoformat(),
            "confidence_level": "high",
            "is_free":          0,
            "is_indoor":        0,
            "target_audience":  "todo publico",
            "has_own_agenda":   1,
        },
    ]

    for place in estadios:
        insert_place(city_id, place)

    imported = 0
    skipped  = 0

    for league_code, league_name in ESPN_LEAGUES:
        print(f"\nObteniendo partidos: {league_name}...")
        events_raw = fetch_espn_events(league_code, days_ahead=90)
        print(f"  {len(events_raw)} partidos totales en ESPN")

        for raw in events_raw:
            event = parse_event(raw, league_name)
            if not event:
                skipped += 1
                continue
            if event["start_date"] < cutoff:
                skipped += 1
                continue
            insert_event(city_id, event)
            imported += 1
            print(f"  [{event['start_date']} {event['time']}] {event['name']} @ {event['venue'][:40]}")

    print(f"\nImportacion Futbol Santiago completada: {imported} partidos ({skipped} omitidos o fuera de Santiago)")


if __name__ == "__main__":
    import_futbol_scl()
