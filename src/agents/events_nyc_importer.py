"""
Importador de eventos públicos de New York City via NYC Open Data.
Dataset: NYC Events (tvpp-9vvx) - Departamento de Parques y eventos especiales.
Solo importa eventos relevantes para turistas: Special Events, Farmers Markets,
Block Parties, Parades, Festivals.
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

SOURCE   = "https://data.cityofnewyork.us/resource/tvpp-9vvx.json"
BASE_URL = "https://www.nycgovparks.org"

GOOD_TYPES = {
    "Special Event":           "Evento / Festival",
    "Farmers Market":          "Mercado / Farmers Market",
    "Block Party":             "Fiesta de Barrio / Evento Local",
    "Parade":                  "Desfile / Parade",
    "Street Event":            "Evento en la Calle",
    "Plaza Partner Event":     "Evento Cultural / Plaza",
    "Open Street Partner Event": "Calle Abierta / Evento",
    "Single Block Festival":   "Festival / Barrio",
    "Athletic Race / Tour":    "Deporte / Carrera",
    "Health Fair":             "Feria de Salud",
    "Street Festival":         "Festival Callejero",
}

SKIP_KEYWORDS = [
    "closed", "maintenance", "mowing", "repair", "inspection",
    "ripa", "tree", "pruning", "renovation", "construction",
    "painting", "plumbing", "electrical", "permit only",
]

TOURIST_KEYWORDS = [
    "festival", "concert", "market", "fair", "parade", "celebration",
    "live", "music", "dance", "art", "film", "movie", "food", "cultural",
    "greenmarket", "smorgasburg", "free", "broadway", "jazz", "show",
    "outdoor", "party", "community", "race", "run", "walk",
]


def is_tourist_relevant(name: str, event_type: str) -> bool:
    nl = name.lower()
    if any(k in nl for k in SKIP_KEYWORDS):
        return False
    # Farmers markets always relevant
    if event_type in ("Farmers Market", "Parade", "Street Festival", "Athletic Race / Tour"):
        return True
    # Special events: only if tourist keywords present or name is interesting
    if event_type == "Special Event":
        if any(k in nl for k in TOURIST_KEYWORDS):
            return True
        # Very short/generic names skip
        if len(name.strip()) < 5 or name.strip().upper() == name.strip():
            return False
        return True
    return True


def parse_dt(dt_str: str) -> tuple:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return dt_str[:10] if dt_str else "", ""


def fetch_events(today: str) -> list:
    all_events = []
    limit = 1000
    offset = 0
    types = list(GOOD_TYPES.keys())
    type_filter = " OR ".join([f"event_type = '{t}'" for t in types])

    print("  Descargando eventos de NYC Open Data...")
    while True:
        try:
            resp = requests.get(SOURCE, params={
                "$limit":  limit,
                "$offset": offset,
                "$where":  f"start_date_time >= '{today}T00:00:00' AND ({type_filter})",
                "$order":  "start_date_time ASC",
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error en offset {offset}: {e}")
            break

        if not data:
            break

        all_events.extend(data)
        offset += limit
        if len(data) < limit or offset >= 8000:
            break

    return all_events


def import_events_nyc():
    today = date.today().isoformat()

    print("\nImportando eventos públicos de New York City...")
    init_db()
    city_id = get_or_create_city("New York City", "United States")

    events_raw = fetch_events(today)
    print(f"  {len(events_raw)} eventos descargados")

    # Deduplicar por nombre+fecha (mismo evento puede aparecer multiple veces)
    seen = set()
    imported = skipped = 0

    for ev in events_raw:
        try:
            name       = ev.get("event_name", "").strip()
            event_type = ev.get("event_type", "")
            borough    = ev.get("event_borough", "")
            location   = ev.get("event_location", "")

            if not name or not is_tourist_relevant(name, event_type):
                skipped += 1
                continue

            start_iso, time_str = parse_dt(ev.get("start_date_time", ""))
            end_iso,   _        = parse_dt(ev.get("end_date_time",   ""))

            if not start_iso:
                skipped += 1
                continue

            dedup_key = f"{name.lower()[:40]}_{start_iso}"
            if dedup_key in seen:
                skipped += 1
                continue
            seen.add(dedup_key)

            category = GOOD_TYPES.get(event_type, "Evento / NYC")
            venue    = location.split(":")[0].strip() if location else f"{borough}, New York, NY"
            address  = f"{location}, {borough}, New York, NY" if location else f"{borough}, New York, NY"

            is_free  = 1 if any(k in name.lower() for k in ["free", "gratuito", "greenmarket"]) else 0
            price    = "Gratuito" if is_free else "Ver NYC Parks para más información"

            safe_id  = re.sub(r"[^a-z0-9]", "", name.lower())[:25]
            event_id = f"nyc_od_{ev.get('event_id', '')}_{safe_id}"

            event = {
                "event_id":         event_id,
                "name":             name[:200],
                "category":         category,
                "venue":            venue[:200],
                "start_date":       start_iso,
                "end_date":         end_iso or start_iso,
                "time":             time_str,
                "price":            price,
                "ticket_source":    BASE_URL,
                "official_source":  SOURCE,
                "status":           "scheduled",
                "confidence_level": "medium",
                "is_free": is_free, "is_indoor": 0, "target_audience": "todos",
            }
            insert_event(city_id, event)
            imported += 1

        except Exception:
            continue

    print(f"\nImportacion eventos NYC completada: {imported} eventos ({skipped} omitidos/duplicados)")


if __name__ == "__main__":
    import_events_nyc()
