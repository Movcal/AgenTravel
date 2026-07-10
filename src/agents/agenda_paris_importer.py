"""
Importador de agenda cultural de París via Open Data de la Mairie de Paris.
Fuente: https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/que-faire-a-paris-/records
"""
import sys, os, re, requests
from datetime import date, datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

SOURCE   = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/que-faire-a-paris-/records"
BASE_URL = "https://www.paris.fr/evenements/"

TAG_CATEGORY = {
    "musique":       "Música / Concierto",
    "concert":       "Música / Concierto",
    "exposition":    "Arte / Exposición",
    "theatre":       "Teatro / Espectáculo",
    "danse":         "Danza / Espectáculo",
    "cinema":        "Cine",
    "enfants":       "Actividades Infantiles",
    "sport":         "Deporte / Actividad Física",
    "conference":    "Conferencia / Charla",
    "visite":        "Visita Guiada / Tour",
    "fete":          "Fiesta / Festival",
    "marche":        "Mercado / Feria",
    "lecture":       "Literatura / Lectura",
    "gratuit":       "Evento Gratuito",
}


def get_category(qfap_tags: str, group: str) -> str:
    combined = ((qfap_tags or "") + " " + (group or "")).lower()
    for key, cat in TAG_CATEGORY.items():
        if key in combined:
            return cat
    return "Evento Cultural"


def parse_dt(dt_str: str) -> tuple:
    """Devuelve (date_iso, time_str) desde ISO 8601."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        dt_local = dt.astimezone(timezone.utc)
        # París = UTC+2 (verano) / UTC+1 (invierno)
        offset = 2 if 4 <= dt_local.month <= 10 else 1
        from datetime import timedelta
        dt_paris = dt_local + timedelta(hours=offset)
        return dt_paris.strftime("%Y-%m-%d"), dt_paris.strftime("%H:%M")
    except Exception:
        try:
            parts = dt_str[:16].replace("T", " ")
            return parts[:10], parts[11:16]
        except Exception:
            return "", ""


def fetch_all_events() -> list:
    """Descarga todos los eventos futuros de la API de París."""
    all_events = []
    limit      = 100
    offset     = 0

    print("  Descargando eventos de París Open Data...")
    while True:
        try:
            resp = requests.get(SOURCE, params={
                "limit":  limit,
                "offset": offset,
                "where":  "date_end > now()",
                "order_by": "date_start ASC",
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error en offset {offset}: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        all_events.extend(results)
        total = data.get("total_count", 0)
        offset += limit
        if offset >= total or offset >= 2000:  # cap a 2000 eventos
            break

    return all_events


def import_agenda_paris():
    today = date.today().isoformat()

    print("\nImportando agenda cultural de París...")
    init_db()
    city_id = get_or_create_city("París", "Francia")

    events_raw = fetch_all_events()
    print(f"  {len(events_raw)} eventos descargados")

    imported = skipped = 0

    for ev in events_raw:
        try:
            title = ev.get("title", "").strip()
            if not title:
                continue

            start_raw = ev.get("date_start", "")
            end_raw   = ev.get("date_end",   "")

            start_iso, time_str = parse_dt(start_raw) if start_raw else ("", "")
            end_iso,   _        = parse_dt(end_raw)   if end_raw   else ("", "")

            if not start_iso:
                continue
            if end_iso and end_iso < today:
                skipped += 1
                continue

            # Categoría
            qfap_tags = ev.get("qfap_tags", "") or ""
            group     = ev.get("group", "") or ""
            category  = get_category(qfap_tags, group)

            # Venue y dirección
            venue   = ev.get("address_name", "").strip() or ev.get("address_zipcode", "Paris")
            address = ev.get("address_street", "").strip()
            cp      = ev.get("address_zipcode", "").strip()
            if address and cp:
                full_address = f"{address}, {cp} Paris"
            elif venue:
                full_address = f"{venue}, Paris"
            else:
                full_address = "Paris"

            # Precio
            price_raw = ev.get("price_type", "")
            is_free   = 1 if price_raw == "gratuit" else 0
            price_str = "Gratuito" if is_free else ev.get("price_detail", "Ver enlace oficial") or "Ver enlace oficial"

            # Link
            url_slug = ev.get("url", "")
            link     = url_slug if url_slug and url_slug.startswith("http") else f"{BASE_URL}{ev.get('id', '')}"

            # Audiencia
            audience_raw = ev.get("audience", "") or ""
            if "enfant" in qfap_tags.lower() or "famille" in qfap_tags.lower() or "tout-petits" in audience_raw.lower():
                audience = "familias"
            else:
                audience = "todos"

            uid      = str(ev.get("id", ev.get("event_id", "")))
            event_id = f"paris_od_{uid}"

            event = {
                "event_id":         event_id,
                "name":             title[:200],
                "category":         category,
                "venue":            (venue or full_address)[:200],
                "start_date":       start_iso,
                "end_date":         end_iso or start_iso,
                "time":             time_str,
                "price":            price_str[:200],
                "ticket_source":    link,
                "official_source":  SOURCE,
                "status":           "active" if start_iso <= today <= (end_iso or start_iso) else "scheduled",
                "confidence_level": "high",
                "is_free": is_free, "is_indoor": 1, "target_audience": audience,
            }
            insert_event(city_id, event)
            imported += 1

        except Exception:
            continue

    print(f"\nImportacion Paris completada: {imported} eventos ({skipped} ya pasados)")


if __name__ == "__main__":
    import_agenda_paris()
