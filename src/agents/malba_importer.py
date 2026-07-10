"""
Importador del MALBA (Museo de Arte Latinoamericano de Buenos Aires).
Fuente: https://malba.org.ar/agenda/ + páginas individuales de /evento/
Scraping de exposiciones y actividades.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://malba.org.ar"
VENUE  = "MALBA - Museo de Arte Latinoamericano de Buenos Aires, Av. Figueroa Alcorta 3415, Buenos Aires"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

PAGES_TO_SCRAPE = [
    f"{SOURCE}/agenda/",
    f"{SOURCE}/cine/",
    f"{SOURCE}/cursos/",
    f"{SOURCE}/conferencias/",
]


def parse_fecha(texto: str) -> str:
    texto = texto.lower().strip()
    # "19 de junio" o "19 de junio de 2026"
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?', texto)
    if m:
        dia, mes_str, anio = m.group(1), m.group(2), m.group(3)
        mes = MESES.get(mes_str)
        if mes:
            try:
                anio_int = int(anio) if anio else date.today().year
                d = date(anio_int, mes, int(dia))
                if not anio and (date.today() - d).days > 60:
                    d = date(anio_int + 1, mes, int(dia))
                return d.isoformat()
            except Exception:
                pass
    # "2026-06-23" o "2026/06/23"
    m2 = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', texto)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return ""


def scrape_event_links() -> set:
    """Recolecta todos los links a /evento/ de las páginas principales."""
    links = set()
    for url in PAGES_TO_SCRAPE:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            html = resp.content.decode("utf-8", errors="replace")
            found = re.findall(r'href="(https://malba\.org\.ar/evento/[^"]+)"', html)
            links.update(found)
        except Exception:
            continue
    return links


def scrape_evento(url: str) -> dict:
    """Scraping de una página individual de evento."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        html = resp.content.decode("utf-8", errors="replace")
    except Exception:
        return {}

    # Título
    titulo = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    titulo_txt = titulo.group(1).strip() if titulo else url.split("/")[-2]

    # Fechas: "Del 19 de junio al 23 de agosto"
    rango = re.search(
        r'Del?\s+(\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)\s+al?\s+(\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)',
        html, re.I
    )
    if rango:
        start_date = parse_fecha(rango.group(1))
        end_date   = parse_fecha(rango.group(2))
    else:
        # Fecha única: "19 de junio de 2026" o datetime en HTML
        fecha_unica = re.search(r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})', html, re.I)
        if fecha_unica:
            start_date = parse_fecha(fecha_unica.group(1))
            end_date = start_date
        else:
            # Buscar en meta og o schema
            m_date = re.search(r'"datePublished":"(\d{4}-\d{2}-\d{2})', html)
            start_date = m_date.group(1) if m_date else ""
            end_date = start_date

    if not start_date:
        return {}

    # Nivel / sala (Nivel 1, Nivel 2, Nivel 3, Terraza)
    nivel = re.search(r'Nivel\s+\d+|Terraza|Sala\s+\w+', html, re.I)
    sala = nivel.group(0) if nivel else ""

    # Gratuito o pago
    is_free = 1 if re.search(r'gratuito|gratis|libre|sin cargo|entrada libre', html, re.I) else 0

    # Público
    audience = "todo publico"
    if re.search(r'ni[ñn]os|infantil|familia', html, re.I):
        audience = "familia"
    elif re.search(r'adultos|profesional|universitario', html, re.I):
        audience = "adultos"

    slug = url.strip("/").split("/")[-1]

    return {
        "slug":        slug,
        "titulo":      titulo_txt,
        "start_date":  start_date,
        "end_date":    end_date,
        "sala":        sala,
        "is_free":     is_free,
        "audience":    audience,
        "link":        url,
    }


def import_malba():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando MALBA (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # --- PLACE: MALBA ---
    place = {
        "name": "MALBA - Museo de Arte Latinoamericano de Buenos Aires",
        "category": "Museo / Arte Contemporáneo",
        "description": "El museo de arte latinoamericano más importante del mundo. Colección permanente de más de 700 obras y exposiciones temporarias internacionales.",
        "opening_hours": "Lun, mié a dom: 12 a 20 h | Jue: 12 a 21 h",
        "closed_days": "Martes",
        "price": "Desde $5.000 ARS (ver malba.org.ar/visita)",
        "currency": "ARS",
        "address": "Av. Figueroa Alcorta 3415, Palermo, Buenos Aires",
        "contact": "Tel: +54 11 4808-6500",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
        "place_slug": "malba",
    }
    insert_place(city_id, place)

    # --- Scraping de eventos ---
    print("Recolectando links de eventos...")
    links = scrape_event_links()
    print(f"  {len(links)} links encontrados")

    imported = 0
    skipped  = 0

    for url in sorted(links):
        ev = scrape_evento(url)
        if not ev or not ev.get("start_date"):
            skipped += 1
            continue
        if ev["end_date"] and ev["end_date"] < cutoff:
            skipped += 1
            continue

        status = "scheduled" if ev["start_date"] >= today.isoformat() else "active"
        price_str = f"Gratuito - ver programa: {ev['link']}" if ev["is_free"] else f"Con cargo - consultar precio: {ev['link']}"
        venue_sala = f"{VENUE} - {ev['sala']}" if ev["sala"] else VENUE

        event = {
            "event_id":        f"malba_{ev['slug']}",
            "name":            ev["titulo"],
            "category":        "Arte / Exposición",
            "venue":           venue_sala,
            "start_date":      ev["start_date"],
            "end_date":        ev["end_date"] or ev["start_date"],
            "time":            "Lun, mié a dom 12-20 h | Jue 12-21 h",
            "price":           price_str,
            "ticket_source":   ev["link"],
            "official_source": SOURCE,
            "status":          status,
            "confidence_level": "high",
            "is_free":         ev["is_free"],
            "is_indoor":       1,
            "target_audience": ev["audience"],
        }
        insert_event(city_id, event)
        imported += 1

    print(f"\nImportacion MALBA completada: {imported} eventos ({skipped} omitidos)")


if __name__ == "__main__":
    import_malba()
