"""
Importador de la agenda oficial de eventos de Rio de Janeiro (Visit.Rio / Riotur).
Fuente: https://visitrio.com.br/wp-json/tribe/events/v1/events
        (API REST del plugin The Events Calendar del sitio oficial de turismo)

Nota: el WAF del sitio bloquea requests sin User-Agent de navegador.
"""
import sys, os, re, html, requests
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

SOURCE  = "https://visitrio.com.br/wp-json/tribe/events/v1/events"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

CATEGORY_MAP = {
    "esportivos":    "Deporte / Competencia",
    "shows":         "Música / Concierto",
    "show":          "Música / Concierto",
    "musica":        "Música / Concierto",
    "culturais":     "Cultural",
    "cultural":      "Cultural",
    "gastronomicos": "Gastronomía / Festival",
    "teatro":        "Teatro / Espectáculo",
    "religiosos":    "Religioso / Tradicional",
    "congressos":    "Congreso / Convención",
}


def clean_text(raw: str) -> str:
    """Quita tags HTML y decodifica entidades (&#8211; -> –)."""
    return html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).strip()


def get_category(categories: list) -> str:
    for c in categories or []:
        slug = (c.get("slug") or "").lower()
        for key, cat in CATEGORY_MAP.items():
            if key in slug:
                return cat
    return "Evento"


def extract_venue(description_html: str) -> str:
    """Busca 'Local: X' en la descripcion. Solo acepta matches cortos y
    que empiecen en mayuscula (los largos suelen ser texto corrido)."""
    desc = clean_text(description_html)
    m = re.search(r"Local[:\s]+([^\n.;|]{4,60})", desc, re.I)
    if m:
        venue = m.group(1).strip()
        if venue and venue[0].isupper():
            return venue
    return "Rio de Janeiro"


def fetch_events() -> list:
    """Descarga todos los eventos futuros paginando la API."""
    today = date.today().isoformat()
    events, page = [], 1
    while page <= 10:  # cap defensivo: 10 paginas x 50 = 500 eventos
        try:
            resp = requests.get(SOURCE, headers=HEADERS, params={
                "per_page": 50, "page": page, "start_date": today,
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error en pagina {page}: {e}")
            break
        batch = data.get("events", [])
        if not batch:
            break
        events.extend(batch)
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return events


def import_agenda_rio():
    today = date.today().isoformat()

    print("\nImportando agenda oficial de Rio (Visit.Rio / Riotur)...")
    init_db()
    city_id = get_or_create_city("Rio de Janeiro", "Brasil")

    events_raw = fetch_events()
    print(f"  {len(events_raw)} eventos descargados")

    imported = 0
    for ev in events_raw:
        try:
            title = clean_text(ev.get("title", ""))
            if not title:
                continue

            start = (ev.get("start_date") or "")[:10]
            end   = (ev.get("end_date") or start)[:10]
            if not start or (end and end < today):
                continue

            time_str = "" if ev.get("all_day") else (ev.get("start_date") or "")[11:16]

            cost = clean_text(ev.get("cost", ""))
            is_free = 1 if re.search(r"grat|grátis|free", cost, re.I) else 0
            price = cost or "Ver enlace oficial"

            link = ev.get("website") or ev.get("url") or ""

            event = {
                "event_id":         f"visitrio_{ev.get('id')}",
                "name":             title[:200],
                "category":         get_category(ev.get("categories")),
                "venue":            extract_venue(ev.get("description", ""))[:200],
                "start_date":       start,
                "end_date":         end or start,
                "time":             time_str,
                "price":            price[:200],
                "ticket_source":    link,
                "official_source":  ev.get("url") or SOURCE,
                "status":           "active" if start <= today <= (end or start) else "scheduled",
                "confidence_level": "high",
                "is_free":          is_free,
                "is_indoor":        None,
                "target_audience":  "todos",
            }
            insert_event(city_id, event)
            imported += 1
        except Exception:
            continue

    print(f"\nImportacion Visit.Rio completada: {imported} eventos")


if __name__ == "__main__":
    import_agenda_rio()
