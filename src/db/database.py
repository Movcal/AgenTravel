import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "agentravel.db")

def normalize_confidence(value: str) -> str:
    if not value:
        return "medium"
    v = value.lower().strip()
    mapping = {
        "high": "high", "alta": "high", "alto": "high",
        "medium": "medium", "media": "medium", "medio": "medium", "moderate": "medium",
        "low": "low", "baja": "low", "bajo": "low",
    }
    return mapping.get(v, "medium")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        schema = f.read()
    conn = get_connection()
    conn.executescript(schema)
    # Migraciones: agregar columnas nuevas a tablas existentes
    for col, coltype in [("is_free", "INTEGER"), ("is_indoor", "INTEGER"), ("target_audience", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass
    for col, coltype in [("is_free", "INTEGER"), ("is_indoor", "INTEGER"), ("target_audience", "TEXT"), ("has_own_agenda", "INTEGER"), ("place_slug", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE places ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass
    conn.close()
    print(f"Base de datos inicializada en: {os.path.abspath(DB_PATH)}")

def get_or_create_city(name: str, country: str = None) -> int:
    conn = get_connection()
    row = conn.execute("SELECT id FROM cities WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
    if row:
        city_id = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO cities (name, country) VALUES (?, ?)", (name, country)
        )
        city_id = cur.lastrowid
        conn.commit()
    conn.close()
    return city_id

def insert_place(city_id: int, place: dict) -> int:
    conn = get_connection()
    slug = place.get("place_slug")
    # Deduplicar por place_slug si está presente, sino por nombre
    # Si hay slug pero no se encuentra por él, buscar por nombre (migración automática)
    existing = None
    if slug:
        existing = conn.execute(
            "SELECT id FROM places WHERE city_id = ? AND place_slug = ?",
            (city_id, slug)
        ).fetchone()
    if not existing:
        existing = conn.execute(
            "SELECT id FROM places WHERE city_id = ? AND LOWER(name) = LOWER(?)",
            (city_id, place.get("name", ""))
        ).fetchone()
    if existing:
        conn.execute(
            """UPDATE places SET
                name=?, category=?, description=?, opening_hours=?, closed_days=?,
                price=?, currency=?, address=?, contact=?, official_website=?,
                source=?, last_verified=?, confidence_level=?,
                is_free=?, is_indoor=?, target_audience=?, has_own_agenda=?, place_slug=?,
                updated_at=datetime('now')
               WHERE id=?""",
            (
                place.get("name"), place.get("category"), place.get("description"),
                place.get("opening_hours"), place.get("closed_days"),
                place.get("price"), place.get("currency"),
                place.get("address"), place.get("contact"),
                place.get("official_website"), place.get("source"),
                place.get("last_verified"), place.get("confidence_level"),
                place.get("is_free"), place.get("is_indoor"),
                place.get("target_audience"), place.get("has_own_agenda"),
                slug, existing["id"]
            )
        )
        conn.commit()
        place_id = existing["id"]
        print(f"  Actualizado: {place.get('name')}".encode('ascii','replace').decode())
    else:
        cur = conn.execute(
            """INSERT INTO places
               (city_id, name, category, description, opening_hours, closed_days,
                price, currency, address, contact, official_website, source,
                last_verified, confidence_level, is_free, is_indoor, target_audience, has_own_agenda, place_slug)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                city_id, place.get("name"), place.get("category"),
                place.get("description"), place.get("opening_hours"),
                place.get("closed_days"), place.get("price"),
                place.get("currency"), place.get("address"),
                place.get("contact"), place.get("official_website"),
                place.get("source"), place.get("last_verified"),
                normalize_confidence(place.get("confidence_level")),
                place.get("is_free"), place.get("is_indoor"),
                place.get("target_audience"), place.get("has_own_agenda"), slug
            )
        )
        conn.commit()
        place_id = cur.lastrowid
        print(f"  Insertado: {place.get('name')}".encode('ascii','replace').decode())
    conn.close()
    return place_id

def insert_event(city_id: int, event: dict) -> int:
    conn = get_connection()
    # Verificar duplicado por event_id externo o nombre+fecha+lugar
    existing = None
    if event.get("event_id"):
        existing = conn.execute(
            "SELECT id FROM events WHERE event_id = ?", (event["event_id"],)
        ).fetchone()
    if not existing:
        existing = conn.execute(
            """SELECT id FROM events WHERE city_id=? AND LOWER(name)=LOWER(?)
               AND start_date=? AND venue=?""",
            (city_id, event.get("name",""), event.get("start_date",""), event.get("venue",""))
        ).fetchone()

    if existing:
        conn.execute(
            """UPDATE events SET
                category=?, venue=?, start_date=?, end_date=?, time=?,
                price=?, ticket_source=?, official_source=?, status=?,
                confidence_level=?, is_free=?, is_indoor=?, target_audience=?,
                updated_at=datetime('now')
               WHERE id=?""",
            (
                event.get("category"), event.get("venue"),
                event.get("start_date"), event.get("end_date"),
                event.get("time"), event.get("price"),
                event.get("ticket_source"), event.get("official_source"),
                event.get("status", "scheduled"), normalize_confidence(event.get("confidence_level")),
                event.get("is_free"), event.get("is_indoor"), event.get("target_audience"),
                existing["id"]
            )
        )
        conn.commit()
        event_id = existing["id"]
        print(f"  Actualizado evento: {event.get('name')}".encode('ascii','replace').decode())
    else:
        cur = conn.execute(
            """INSERT INTO events
               (event_id, city_id, name, category, venue, start_date, end_date,
                time, price, ticket_source, official_source, status, confidence_level,
                is_free, is_indoor, target_audience)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event.get("event_id"), city_id, event.get("name"),
                event.get("category"), event.get("venue"),
                event.get("start_date"), event.get("end_date"),
                event.get("time"), event.get("price"),
                event.get("ticket_source"), event.get("official_source"),
                event.get("status", "scheduled"), normalize_confidence(event.get("confidence_level")),
                event.get("is_free"), event.get("is_indoor"), event.get("target_audience")
            )
        )
        conn.commit()
        event_id = cur.lastrowid
        print(f"  Insertado evento: {event.get('name')}".encode('ascii','replace').decode())
    conn.close()
    return event_id

def get_city_summary(city_name: str) -> dict:
    conn = get_connection()
    city = conn.execute(
        "SELECT * FROM cities WHERE LOWER(name) = LOWER(?)", (city_name,)
    ).fetchone()
    if not city:
        conn.close()
        return {"error": f"Ciudad '{city_name}' no encontrada"}
    places_count = conn.execute(
        "SELECT COUNT(*) as c FROM places WHERE city_id=?", (city["id"],)
    ).fetchone()["c"]
    events_count = conn.execute(
        "SELECT COUNT(*) as c FROM events WHERE city_id=? AND status IN ('scheduled','active')",
        (city["id"],)
    ).fetchone()["c"]
    conn.close()
    return {
        "city": city["name"],
        "country": city["country"],
        "places": places_count,
        "active_events": events_count
    }

if __name__ == "__main__":
    init_db()
