"""
Importador del Museo Nacional de Bellas Artes (MNBA).
Fuente: https://bellasartes.gob.ar/agenda/
Scraping de agenda publica con visitas guiadas y actividades.
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

BASE_URL   = "https://bellasartes.gob.ar/agenda/"
SOURCE     = "https://bellasartes.gob.ar"
VENUE      = "Museo Nacional de Bellas Artes, Av. del Libertador 1473, Buenos Aires"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}


def parse_fecha_mnba(texto: str) -> str:
    """Convierte '5 de mayo de 2026' o '11 de julio de 2026' a YYYY-MM-DD."""
    texto = texto.lower().strip()
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', texto)
    if m:
        dia, mes_str, anio = m.group(1), m.group(2), m.group(3)
        mes = MESES.get(mes_str)
        if mes:
            try:
                return date(int(anio), mes, int(dia)).isoformat()
            except Exception:
                pass
    return date.today().isoformat()


def parse_hora_mnba(texto: str) -> str:
    """Extrae hora del texto, ej: 'de 11 a 19.30' o 'a las 16 h'."""
    m = re.search(r'a las\s+(\d{1,2}(?:[.:]\d{2})?)\s*h', texto.lower())
    if m:
        return m.group(1).replace('.', ':')
    m = re.search(r'de\s+(\d{1,2}(?:[.:]\d{2})?)\s+a\s+(\d{1,2}(?:[.:]\d{2})?)', texto.lower())
    if m:
        return f"{m.group(1).replace('.', ':')} - {m.group(2).replace('.', ':')}"
    return ""


def detect_audience(titulo: str) -> str:
    t = titulo.lower()
    if "infancia" in t or "niños" in t or "chicos" in t:
        return "familia"
    if "jóvenes" in t or "jovenes" in t or "adolescente" in t:
        return "jovenes"
    if "mayores" in t or "senior" in t:
        return "adultos mayores"
    return "todo publico"


def scrape_agenda() -> list:
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("utf-8", errors="replace")

    eventos = []
    # Extraer cards: titulo, dias, rango de fechas, link
    pattern = r'href=\"(/agenda/[^\"]+)\"[^>]*>.*?<h3 class=\"card-title[^\"]*\">([^<]+)</h3>.*?<span class=\"dias_friendly\">([^<]+)</span>.*?Del ([^<]+)<'
    matches = re.findall(pattern, html, re.DOTALL)

    for url_path, titulo, dias, rango in matches:
        titulo = titulo.strip()
        dias   = dias.strip()
        rango  = rango.strip()

        # Extraer start_date y end_date del rango
        fechas = re.findall(r'\d{1,2}\s+de\s+\w+\s+de\s+\d{4}', rango)
        if len(fechas) >= 2:
            start_date = parse_fecha_mnba(fechas[0])
            end_date   = parse_fecha_mnba(fechas[1])
        elif len(fechas) == 1:
            start_date = parse_fecha_mnba(fechas[0])
            end_date   = start_date
        else:
            continue

        hora   = parse_hora_mnba(rango)
        link   = f"{SOURCE}{url_path}"
        slug   = url_path.strip("/").split("/")[-1]

        eventos.append({
            "slug":        slug,
            "titulo":      titulo,
            "dias":        dias,
            "start_date":  start_date,
            "end_date":    end_date,
            "hora":        hora,
            "link":        link,
        })

    return eventos


def import_mnba():
    today = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nDescargando agenda del MNBA (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # Registrar el MNBA como place
    place = {
        "name": "Museo Nacional de Bellas Artes (MNBA)",
        "category": "Museo / Arte",
        "description": "El museo de arte mas importante de Argentina. Coleccion permanente de arte argentino e internacional desde el siglo XII hasta el XX.",
        "opening_hours": "Mar a vie 11-19:30 h | Sab y dom 10-19:30 h",
        "closed_days": "Lunes",
        "price": "Gratuito",
        "currency": "ARS",
        "address": "Av. del Libertador 1473, Recoleta, Buenos Aires",
        "contact": "Tel: +54 11 5288-9900",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 1,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
        "place_slug": "mnba",
    }
    insert_place(city_id, place)

    eventos = scrape_agenda()
    print(f"Actividades encontradas: {len(eventos)}")

    imported = 0
    skipped  = 0
    seen     = set()

    for ev in eventos:
        if ev["end_date"] < cutoff:
            skipped += 1
            continue

        # Deduplicar por slug+fecha
        key = f"{ev['slug']}_{ev['start_date']}"
        if key in seen:
            continue
        seen.add(key)

        status = "scheduled" if ev["start_date"] >= today.isoformat() else "active"
        is_horario = "horario" in ev["titulo"].lower()

        event = {
            "event_id":       f"mnba_{ev['slug']}_{ev['start_date']}",
            "name":           ev["titulo"],
            "category":       "Museo / Visita guiada" if "visita" in ev["titulo"].lower() else "Museo / Actividad",
            "venue":          VENUE,
            "start_date":     ev["start_date"],
            "end_date":       ev["end_date"],
            "time":           f"{ev['hora']} ({ev['dias']})" if ev["hora"] else ev["dias"],
            "price":          f"Gratuito - ver programa: {ev['link']}",
            "ticket_source":  ev["link"],
            "official_source": SOURCE,
            "status":         status,
            "confidence_level": "high",
            "is_free":        1,
            "is_indoor":      1,
            "target_audience": detect_audience(ev["titulo"]),
        }
        insert_event(city_id, event)
        imported += 1

    print(f"\nImportacion completada: {imported} actividades del MNBA ({skipped} anteriores a {cutoff} omitidas)")


if __name__ == "__main__":
    import_mnba()
