"""
Importador del Estadio Monumental (River Plate).
- Place: Estadio Más Monumental y Museo
- Events: Partidos de River en el Monumental via API oficial
  https://www.riverplate.com/api/v1/sports/opta/matches/recent-and-upcoming
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

API_PARTIDOS   = "https://www.riverplate.com/api/v1/sports/opta/matches/recent-and-upcoming"
SOURCE         = "https://www.cariverplate.com.ar"
SOURCE_TICKETS = "https://www.cariverplate.com.ar/entradas"
VENUE_ESTADIO  = "Estadio Más Monumental, Av. Figueroa Alcorta 7597, Núñez, Buenos Aires"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_partidos() -> dict:
    resp = requests.get(API_PARTIDOS, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {})


def import_monumental():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando Estadio Monumental / River Plate (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # --- PLACE: Estadio Más Monumental ---
    place_estadio = {
        "name": "Estadio Más Monumental (River Plate)",
        "category": "Estadio / Icono Cultural",
        "description": "El estadio con mayor capacidad de Argentina y uno de los más grandes de Sudamérica (84.000 espectadores). Sede de River Plate y escenario de partidos históricos incluida la Final del Mundial 1978.",
        "opening_hours": "Visitas guiadas y museo: lunes a domingo 10 a 18 h",
        "closed_days": "Dias de partido (consultar antes de ir)",
        "price": "Ver en cariverplate.com.ar/museo",
        "currency": "ARS",
        "address": "Av. Figueroa Alcorta 7597, Núñez, Buenos Aires",
        "contact": "cariverplate.com.ar",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 0,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
        "place_slug": "estadio_monumental",
    }
    insert_place(city_id, place_estadio)

    # --- PLACE: Museo Monumental ---
    place_museo = {
        "name": "Museo Monumental (River Plate)",
        "category": "Museo / Deportivo",
        "description": "Museo oficial de River Plate con trofeos, historia del club, camisetas históricas y recorrido por el estadio.",
        "opening_hours": "Lunes a domingo 10 a 18 h",
        "closed_days": "Dias de partido profesional",
        "price": "Ver en cariverplate.com.ar/museo",
        "currency": "ARS",
        "address": "Av. Figueroa Alcorta 7597, Núñez, Buenos Aires",
        "contact": "cariverplate.com.ar/museo",
        "official_website": f"{SOURCE}/museo",
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 0,
        "place_slug": "museo_monumental",
    }
    insert_place(city_id, place_museo)

    # --- Visita guiada como evento recurrente ---
    visita = {
        "event_id":        "river_visita_guiada_2026",
        "name":            "Visita guiada: Museo + Estadio Monumental",
        "category":        "Turismo / Visita Guiada",
        "venue":           VENUE_ESTADIO,
        "start_date":      today.isoformat(),
        "end_date":        f"{today.year}-12-31",
        "time":            "Lunes a domingo 10:00 - 18:00 h",
        "price":           f"Con cargo - consultar precio: {SOURCE}/museo",
        "ticket_source":   f"{SOURCE}/museo",
        "official_source": SOURCE,
        "status":          "active",
        "confidence_level": "high",
        "is_free":         0,
        "is_indoor":       0,
        "target_audience": "todo publico",
    }
    insert_event(city_id, visita)

    # --- EVENTS: Partidos de River en el Monumental ---
    print("\nDescargando fixture de River Plate...")
    try:
        data = fetch_partidos()
    except Exception as e:
        print(f"  Error al obtener partidos: {e}")
        return

    upcoming = data.get("upcoming", [])
    last = data.get("last_played")
    partidos = ([last] if last else []) + upcoming

    imported = 0
    skipped  = 0

    for partido in partidos:
        try:
            match_date = partido.get("match_date", "")[:10]
            if match_date < cutoff:
                skipped += 1
                continue

            # Solo importar partidos EN el Monumental
            venue_nombre = partido.get("venue_name", "")
            if "Monumental" not in venue_nombre and "monumental" not in venue_nombre.lower():
                # Partido de visitante — registrar igual pero con venue real
                venue = f"{venue_nombre}, Argentina" if venue_nombre else VENUE_ESTADIO
            else:
                venue = VENUE_ESTADIO

            home = partido.get("home_team_name", "")
            away = partido.get("away_team_name", "")
            hora = partido.get("match_date", "")[11:16] if len(partido.get("match_date", "")) > 10 else ""
            match_id = partido.get("match_uuid", partido.get("id", ""))
            comp = partido.get("competition_name") or partido.get("competition", {}).get("name", "Liga Argentina")

            nombre_evento = f"{home} vs {away}"
            status = "scheduled" if match_date >= today.isoformat() else "completed"

            event = {
                "event_id":        f"river_match_{match_id}",
                "name":            nombre_evento,
                "category":        f"Fútbol / {comp}",
                "venue":           venue,
                "start_date":      match_date,
                "end_date":        match_date,
                "time":            hora,
                "price":           f"Con cargo - comprar entradas: {SOURCE_TICKETS}",
                "ticket_source":   SOURCE_TICKETS,
                "official_source": SOURCE,
                "status":          status,
                "confidence_level": "high",
                "is_free":         0,
                "is_indoor":       0,
                "target_audience": "todo publico",
            }
            insert_event(city_id, event)
            imported += 1

        except Exception as e:
            print(f"  Error en partido: {e}")
            skipped += 1
            continue

    print(f"\nImportacion Monumental completada:")
    print(f"  Partidos importados: {imported} ({skipped} omitidos)")


if __name__ == "__main__":
    import_monumental()
