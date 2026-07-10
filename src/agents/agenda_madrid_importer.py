"""
Importador de agenda cultural de Madrid via Open Data del Ayuntamiento de Madrid.
Fuente: https://datos.madrid.es/egob/catalogo/300107-0-agenda-actividades-eventos.json
Cobre eventos culturales, espectáculos, exposiciones y actividades gratuitas.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

SOURCE = "https://datos.madrid.es/egob/catalogo/300107-0-agenda-actividades-eventos.json"

TYPE_MAP = {
    "CineActividadesAudiovisuales": "Cine / Audiovisual",
    "ExposicionesActividadesArtes":  "Arte / Exposición",
    "MusicaActividadesMusicales":    "Música / Concierto",
    "TeatroDanzaEspectaculos":       "Teatro / Danza / Espectáculo",
    "ActividadesCulturalesYLudicas": "Cultura / Ocio",
    "DeportesActividadesDeportivas": "Deporte / Actividad Física",
    "CursosFormacion":               "Cursos / Formación",
    "ActividadesInfantiles":         "Actividades Infantiles / Familia",
    "FeriasYMercados":               "Ferias / Mercados",
}


def get_category(raw_type: str) -> str:
    for key, cat in TYPE_MAP.items():
        if key.lower() in raw_type.lower():
            return cat
    return "Evento Cultural"


def parse_date(dt_str: str) -> tuple:
    """Devuelve (date_iso, time_str) desde '2026-07-15 20:00:00.0'."""
    try:
        parts = dt_str.strip().split(" ")
        date_iso = parts[0]
        time_str = parts[1][:5] if len(parts) > 1 else ""
        return date_iso, time_str
    except Exception:
        return "", ""


def fetch_events() -> list:
    try:
        resp = requests.get(SOURCE, timeout=30)
        resp.raise_for_status()
        return resp.json().get("@graph", [])
    except Exception as e:
        print(f"  Error descargando agenda: {e}")
        return []


def import_agenda_madrid():
    today  = date.today().isoformat()

    print("\nImportando agenda cultural de Madrid (Open Data)...")
    init_db()
    city_id = get_or_create_city("Madrid", "España")

    events_raw = fetch_events()
    print(f"  {len(events_raw)} eventos descargados")

    imported = skipped_past = skipped_future = 0

    for ev in events_raw:
        try:
            title    = ev.get("title", "").strip()
            if not title:
                continue

            start_iso, time_str = parse_date(ev.get("dtstart", ""))
            end_iso,   _        = parse_date(ev.get("dtend",   ""))

            if not start_iso:
                continue

            # Saltar eventos ya pasados
            if end_iso and end_iso < today:
                skipped_past += 1
                continue

            # Saltar eventos muy lejanos (más de 1 año)
            if start_iso > f"{int(today[:4])+1}-12-31":
                skipped_future += 1
                continue

            # Hora: preferir campo time del API sobre la derivada del dtstart
            api_time = ev.get("time", "")
            hora = api_time if api_time else time_str

            # Categoría
            raw_type = ev.get("@type", "")
            category = get_category(raw_type)

            # Venue
            venue = ev.get("event-location", "").strip()
            if not venue:
                addr = ev.get("address", {}).get("area", {})
                venue = addr.get("street-address", "") + ", Madrid"

            # Dirección
            addr_obj = ev.get("address", {}).get("area", {})
            street   = addr_obj.get("street-address", "")
            cp       = addr_obj.get("postal-code", "")
            address  = f"{street}, {cp} Madrid".strip(", ") if street else "Madrid"

            # Precio
            raw_price = ev.get("price", "").strip()
            is_free   = int(ev.get("free", 0))
            if is_free:
                price = "Gratuito"
            elif raw_price:
                price = raw_price
            else:
                price = "Ver enlace oficial"

            link = ev.get("link", "https://www.madrid.es") or "https://www.madrid.es"

            # Audiencia
            audience_raw = ev.get("audience", "").strip()
            if "Niños" in audience_raw or "Familias" in audience_raw:
                audience = "familias"
            elif "Jóvenes" in audience_raw:
                audience = "jóvenes"
            else:
                audience = "todos"

            uid      = ev.get("uid", ev.get("id", ""))
            event_id = f"madopendata_{uid}"

            event = {
                "event_id":         event_id,
                "name":             title,
                "category":         category,
                "venue":            venue[:200] if venue else "Madrid",
                "start_date":       start_iso,
                "end_date":         end_iso or start_iso,
                "time":             hora,
                "price":            price[:200],
                "ticket_source":    link,
                "official_source":  SOURCE,
                "status":           "active" if start_iso <= today <= (end_iso or start_iso) else "scheduled",
                "confidence_level": "high",
                "is_free": is_free, "is_indoor": 1, "target_audience": audience,
            }
            insert_event(city_id, event)
            imported += 1

        except Exception as e:
            continue

    print(f"\nImportacion completada: {imported} eventos importados")
    print(f"  Omitidos (pasados): {skipped_past} | Omitidos (muy futuros): {skipped_future}")


if __name__ == "__main__":
    import_agenda_madrid()
