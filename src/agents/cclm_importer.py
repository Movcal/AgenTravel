"""
Importador del Centro Cultural La Moneda (CCLM).
Fuente: https://www.ccplm.cl/sitio/programacion/
El CCLM está en el subterráneo del Palacio de La Moneda.
Exposiciones de arte, fotografía y diseño mayormente gratuitas.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://www.ccplm.cl"
VENUE  = "Centro Cultural La Moneda (CCLM), Plaza de la Ciudadanía 26, Santiago Centro"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MESES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12
}


def parse_fecha(texto: str) -> str:
    texto = texto.lower().strip()
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
    m2 = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', texto)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return ""


def try_wp_api() -> list:
    """Intenta WP API del CCLM."""
    events = []
    for endpoint in [
        f"{SOURCE}/wp-json/wp/v2/exposicion",
        f"{SOURCE}/wp-json/wp/v2/exposiciones",
        f"{SOURCE}/wp-json/wp/v2/mec-events",
        f"{SOURCE}/wp-json/wp/v2/posts",
    ]:
        try:
            resp = requests.get(endpoint, params={"per_page": 100},
                                headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    print(f"  WP API: {endpoint} ({len(data)} items)")
                    return data
        except Exception:
            continue
    return events


def scrape_programacion() -> list:
    """Scraping HTML de la programación del CCLM."""
    eventos = []
    urls_to_try = [
        f"{SOURCE}/sitio/programacion/",
        f"{SOURCE}/programacion/",
        f"{SOURCE}/exposiciones/",
    ]

    html = ""
    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                html = resp.content.decode("utf-8", errors="replace")
                print(f"  Página encontrada: {url}")
                break
        except Exception:
            continue

    if not html:
        return []

    # Buscar links a exposiciones/eventos
    links = set(re.findall(
        r'href="(https://(?:www\.)?ccplm\.cl/[^"]*(?:exposicion|evento|actividad|obra)[^"]*)"',
        html, re.I
    ))
    if not links:
        links_rel = re.findall(
            r'href="(/[^"]*(?:exposicion|evento|actividad|obra|sitio)[^"]*)"',
            html, re.I
        )
        links = {f"{SOURCE}{l}" for l in links_rel if len(l) > 5}

    # También buscar cards directamente en el HTML
    # Patrón típico: título + rango de fechas en card
    cards = re.findall(
        r'<h\d[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h\d>.*?'
        r'(\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)',
        html, re.DOTALL | re.I
    )
    for titulo, fecha_txt in cards[:20]:
        start_date = parse_fecha(fecha_txt)
        if start_date:
            slug = re.sub(r'[^a-z0-9]+', '_', titulo.lower().strip())[:30]
            eventos.append({
                "slug": slug,
                "titulo": titulo.strip(),
                "start_date": start_date,
                "end_date": start_date,
                "is_free": 1,
                "link": f"{SOURCE}/programacion/",
            })

    # Scrapear links individuales
    for url in sorted(links)[:20]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            h = r.content.decode("utf-8", errors="replace")

            titulo = re.search(r'<h1[^>]*>([^<]+)</h1>', h)
            if not titulo:
                continue
            titulo_txt = titulo.group(1).strip()

            fechas = re.findall(r'\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?', h, re.I)
            start_date = parse_fecha(fechas[0]) if fechas else ""
            end_date   = parse_fecha(fechas[-1]) if len(fechas) > 1 else start_date

            if not start_date:
                continue

            is_free = 1 if re.search(r'gratuito|gratis|libre|sin costo', h, re.I) else 0
            slug = url.strip("/").split("/")[-1]

            eventos.append({
                "slug": slug,
                "titulo": titulo_txt,
                "start_date": start_date,
                "end_date": end_date or start_date,
                "is_free": is_free,
                "link": url,
            })
        except Exception:
            continue

    return eventos


def import_cclm():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando Centro Cultural La Moneda - CCLM (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Santiago de Chile", "Chile")

    # --- PLACE: CCLM ---
    place = {
        "name": "Centro Cultural La Moneda (CCLM)",
        "place_slug": "cclm_scl",
        "category": "Centro Cultural / Museo / Arte",
        "description": "Centro cultural subterráneo bajo el Palacio de La Moneda. Exposiciones de arte, fotografía, diseño y artesanía. Sala de cine, tienda de artesanías y plaza ciudadana. Mayormente gratuito. Ubicado en el corazón cívico de Santiago.",
        "opening_hours": "Mar a dom: 9 a 19 h",
        "closed_days": "Lunes",
        "price": "Gratuito (mayoría de exposiciones) / Algunas muestras con cargo",
        "currency": "CLP",
        "address": "Plaza de la Ciudadanía 26, Santiago Centro (entrada bajo La Moneda)",
        "contact": "ccplm.cl | Tel: +56 2 2355-6500",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 1,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
    }
    insert_place(city_id, place)

    # --- Intentar WP API ---
    print("Intentando WP API...")
    wp_events = try_wp_api()

    imported = 0
    skipped  = 0

    if wp_events:
        for raw in wp_events:
            try:
                title = re.sub(r'<[^>]+>', '', raw.get("title", {}).get("rendered", "")).strip()
                if not title:
                    continue
                pub_date = raw.get("date", "")[:10]
                link = raw.get("link", f"{SOURCE}/programacion/")
                slug = raw.get("slug", f"cclm_{raw.get('id', '')}")

                if pub_date < cutoff:
                    skipped += 1
                    continue

                event = {
                    "event_id":        f"cclm_{slug}",
                    "name":            title,
                    "category":        "Arte / Exposición CCLM",
                    "venue":           VENUE,
                    "start_date":      pub_date,
                    "end_date":        pub_date,
                    "time":            "Mar a dom 9-19 h",
                    "price":           f"Gratuito - ver programa: {link}",
                    "ticket_source":   link,
                    "official_source": SOURCE,
                    "status":          "scheduled" if pub_date >= today.isoformat() else "active",
                    "confidence_level": "high",
                    "is_free": 1, "is_indoor": 1, "target_audience": "todo publico",
                }
                insert_event(city_id, event)
                imported += 1
            except Exception:
                skipped += 1
    else:
        print("  WP API no disponible. Scraping HTML...")
        eventos = scrape_programacion()
        print(f"  {len(eventos)} eventos encontrados")

        seen = set()
        for ev in eventos:
            if ev["end_date"] < cutoff:
                skipped += 1
                continue
            key = f"{ev['slug']}_{ev['start_date']}"
            if key in seen:
                continue
            seen.add(key)

            price_str = "Gratuito" if ev["is_free"] else f"Con cargo - consultar: {ev['link']}"
            status = "scheduled" if ev["start_date"] >= today.isoformat() else "active"

            event = {
                "event_id":        f"cclm_{ev['slug']}_{ev['start_date']}",
                "name":            ev["titulo"],
                "category":        "Arte / Exposición CCLM",
                "venue":           VENUE,
                "start_date":      ev["start_date"],
                "end_date":        ev["end_date"],
                "time":            "Mar a dom 9-19 h",
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

    print(f"\nImportacion CCLM completada: {imported} exposiciones ({skipped} omitidas)")


if __name__ == "__main__":
    import_cclm()
