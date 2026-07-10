"""
Importador del Centro Cultural Gabriela Mistral (GAM).
Fuente: https://gam.cl/programacion/
El GAM es el principal centro cultural público de Santiago.
Intenta WP API primero, luego scraping HTML.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://gam.cl"
VENUE  = "Centro Cultural Gabriela Mistral (GAM), Av. Libertador Bernardo O'Higgins 227, Santiago"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}


def parse_fecha(texto: str) -> str:
    texto = texto.lower().strip()
    # "19 de junio de 2026" o "19 de junio"
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
    # "2026-07-19" o "2026/07/19"
    m2 = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', texto)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return ""


def detect_is_free(text: str) -> int:
    t = text.lower()
    if any(k in t for k in ["gratuito", "gratis", "entrada liberada", "sin costo", "libre"]):
        return 1
    if any(k in t for k in ["entrada general", "compra tu entrada", "ticketmaster", "puntoticket"]):
        return 0
    return 1  # GAM por defecto es gratuito (centro cultural público)


def detect_audience(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["niños", "infantil", "familia", "para chicos"]):
        return "familia"
    if any(k in t for k in ["jóvenes", "jovenes", "adolescentes"]):
        return "jovenes"
    return "todo publico"


def fetch_wp_events(max_pages: int = 10) -> list:
    """Intenta obtener eventos via WP REST API."""
    events = []
    # GAM puede usar mec-events (Modern Events Calendar plugin) o posts genéricos
    for endpoint in [
        f"{SOURCE}/wp-json/wp/v2/mec-events",
        f"{SOURCE}/wp-json/wp/v2/evento",
        f"{SOURCE}/wp-json/wp/v2/eventos",
        f"{SOURCE}/wp-json/tribe/events/v1/events",
    ]:
        try:
            resp = requests.get(endpoint, params={"per_page": 100, "page": 1},
                                headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"  WP API encontrada: {endpoint} ({len(data)} eventos)")
                    events.extend(data)
                    # Paginar
                    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                    for page in range(2, min(total_pages + 1, max_pages + 1)):
                        r2 = requests.get(endpoint, params={"per_page": 100, "page": page},
                                          headers=HEADERS, timeout=15)
                        if r2.status_code == 200:
                            events.extend(r2.json())
                    return events
        except Exception:
            continue
    return events


GAM_CATEGORY_URLS = [
    f"{SOURCE}/es/que-hacer-en-gam/teatro/",
    f"{SOURCE}/es/que-hacer-en-gam/musica-clasica/",
    f"{SOURCE}/es/que-hacer-en-gam/familiar/",
    f"{SOURCE}/es/que-hacer-en-gam/actividades/",
    f"{SOURCE}/es/que-hacer-en-gam/festivales-eventos-residentes/",
    f"{SOURCE}/es/que-hacer-en-gam/danza/",
    f"{SOURCE}/es/que-hacer-en-gam/musica/",
    f"{SOURCE}/es/que-hacer-en-gam/artes-visuales/",
]


def scrape_html_programacion() -> list:
    """Scraping HTML de las páginas de categoría de GAM."""
    all_links = set()

    for cat_url in GAM_CATEGORY_URLS:
        try:
            resp = requests.get(cat_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            html = resp.content.decode("utf-8", errors="replace")
            # Links internos de GAM con más de 4 segmentos (son obras individuales)
            found = re.findall(r'href="(https://gam\.cl/es/que-hacer-en-gam/[^"]+)"', html)
            for l in found:
                parts = l.rstrip("/").split("/")
                if len(parts) >= 7:  # /es/que-hacer-en-gam/categoria/obra = 7 partes
                    all_links.add(l)
        except Exception:
            continue

    print(f"  Links de eventos GAM encontrados: {len(all_links)}")
    links = all_links
    eventos = []

    for url in sorted(links)[:50]:  # Limitar a 50 para no sobrecargar
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            h = r.content.decode("utf-8", errors="replace")

            titulo = re.search(r'<h1[^>]*>([^<]+)</h1>', h)
            titulo_txt = titulo.group(1).strip() if titulo else url.split("/")[-2]

            # Buscar fechas
            fecha_m = re.search(
                r'(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?',
                h, re.I
            )
            if not fecha_m:
                continue

            start_date = parse_fecha(fecha_m.group(0))
            if not start_date:
                continue

            is_free = detect_is_free(h)
            slug = url.strip("/").split("/")[-1]

            eventos.append({
                "slug": slug,
                "titulo": titulo_txt,
                "start_date": start_date,
                "end_date": start_date,
                "is_free": is_free,
                "link": url,
            })
        except Exception:
            continue

    return eventos


def import_gam():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando GAM - Centro Cultural Gabriela Mistral (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Santiago de Chile", "Chile")

    # --- PLACE: GAM ---
    place = {
        "name": "Centro Cultural Gabriela Mistral (GAM)",
        "place_slug": "gam_scl",
        "category": "Centro Cultural / Artes Escénicas",
        "description": "El principal centro cultural público de Santiago. Sede de teatro, danza, música, artes visuales y cine. Inaugurado en 2010 para el Bicentenario, en el edificio histórico de la UNCTAD III. Programación mayormente gratuita.",
        "opening_hours": "Mar a dom: 9 a 21 h. Eventos según programación.",
        "closed_days": "Lunes",
        "price": "Mayoría de eventos gratuitos / Algunos espectáculos con cargo - ver gam.cl",
        "currency": "CLP",
        "address": "Av. Libertador Bernardo O'Higgins 227, Santiago Centro",
        "contact": "gam.cl | Tel: +56 2 2566-5500",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": None,  # Mixto
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
    }
    insert_place(city_id, place)

    # --- Intentar WP API ---
    print("Intentando WP API...")
    wp_events = fetch_wp_events()

    imported = 0
    skipped  = 0

    if wp_events:
        print(f"  {len(wp_events)} eventos via WP API")
        for raw in wp_events:
            try:
                title = re.sub(r'<[^>]+>', '', raw.get("title", {}).get("rendered", "")).strip()
                if not title:
                    skipped += 1
                    continue

                pub_date = raw.get("date", "")[:10]
                link = raw.get("link", f"{SOURCE}/programacion/")

                # Intentar extraer fecha del evento (MEC plugin fields)
                mec = raw.get("mec", {})
                start_date = mec.get("date", {}).get("start", {}).get("date", pub_date) if mec else pub_date
                end_date   = mec.get("date", {}).get("end",   {}).get("date", start_date) if mec else start_date

                if not start_date:
                    start_date = pub_date
                    end_date   = pub_date

                if end_date < cutoff:
                    skipped += 1
                    continue

                excerpt = re.sub(r'<[^>]+>', '', raw.get("excerpt", {}).get("rendered", "")).strip()
                is_free = detect_is_free(excerpt + " " + title)
                audience = detect_audience(excerpt + " " + title)
                slug = raw.get("slug", f"gam_{raw.get('id', '')}")

                event = {
                    "event_id":        f"gam_{slug}",
                    "name":            title,
                    "category":        "Cultural / GAM",
                    "venue":           VENUE,
                    "start_date":      start_date,
                    "end_date":        end_date,
                    "time":            "",
                    "price":           "Gratuito" if is_free else f"Con cargo - consultar precio: {link}",
                    "ticket_source":   link,
                    "official_source": SOURCE,
                    "status":          "scheduled" if start_date >= today.isoformat() else "active",
                    "confidence_level": "high",
                    "is_free":         is_free,
                    "is_indoor":       1,
                    "target_audience": audience,
                }
                insert_event(city_id, event)
                imported += 1
            except Exception:
                skipped += 1
    else:
        # Fallback: scraping HTML
        print("  WP API no disponible. Intentando scraping HTML...")
        eventos = scrape_html_programacion()
        print(f"  {len(eventos)} eventos encontrados via HTML")

        for ev in eventos:
            if ev["end_date"] < cutoff:
                skipped += 1
                continue

            status = "scheduled" if ev["start_date"] >= today.isoformat() else "active"
            price_str = "Gratuito" if ev["is_free"] else f"Con cargo - consultar precio: {ev['link']}"

            event = {
                "event_id":        f"gam_{ev['slug']}_{ev['start_date']}",
                "name":            ev["titulo"],
                "category":        "Cultural / GAM",
                "venue":           VENUE,
                "start_date":      ev["start_date"],
                "end_date":        ev["end_date"],
                "time":            "",
                "price":           price_str,
                "ticket_source":   ev["link"],
                "official_source": SOURCE,
                "status":          status,
                "confidence_level": "medium",
                "is_free":         ev["is_free"],
                "is_indoor":       1,
                "target_audience": "todo publico",
            }
            insert_event(city_id, event)
            imported += 1

    print(f"\nImportacion GAM completada: {imported} eventos ({skipped} omitidos)")


if __name__ == "__main__":
    import_gam()
