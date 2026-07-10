"""
Importador del Museo Nacional de Bellas Artes de Chile (MNBA).
Fuente: https://www.mnba.gob.cl/cartelera/
Drupal CMS — fechas en <time datetime="..."> y JSON-LD startDate/endDate.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://www.mnba.gob.cl"
VENUE  = "Museo Nacional de Bellas Artes de Chile (MNBA), Parque Forestal s/n, Santiago"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

EXCLUDED_SLUGS = {"proximos", "pasados", "red-nacional"}


def parse_dates_from_html(html: str) -> tuple:
    """
    Extrae startDate y endDate del HTML de una página de MNBA Chile.
    Prioridad:
      1. JSON-LD: "startDate": "YYYY-MM-DD HH:MM"
      2. <time datetime="YYYY-MM-DDTHH:MM:SSZ">
    Retorna (start_date, end_date) en formato 'YYYY-MM-DD' o '' si no hay.
    """
    # 1. JSON-LD
    start = re.search(r'"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    end   = re.search(r'"endDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    if start:
        return start.group(1), (end.group(1) if end else start.group(1))

    # 2. <time datetime="2026-07-18T...">
    datetimes = re.findall(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})T', html)
    if datetimes:
        return datetimes[0], datetimes[-1]

    return "", ""


def parse_title_from_html(html: str, slug: str) -> str:
    """Extrae el titulo del og:title, h1, o del slug."""
    og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    if og:
        return og.group(1).strip()
    h1 = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    if h1:
        return h1.group(1).strip()
    return slug.replace("-", " ").title()


def scrape_cartelera() -> list:
    """Scraping de la cartelera del MNBA Chile."""
    eventos = []

    all_links = set()
    for url in [f"{SOURCE}/cartelera/", f"{SOURCE}/cartelera/proximos"]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue
            h = resp.content.decode("utf-8", errors="replace")
            found = re.findall(r'href="(/cartelera/[^"]+)"', h)
            for l in found:
                slug = l.strip("/").split("/")[-1]
                if slug not in EXCLUDED_SLUGS:
                    all_links.add(l)
        except Exception:
            continue

    print(f"  Links encontrados: {len(all_links)}")

    for path in sorted(all_links):
        slug = path.strip("/").split("/")[-1]
        full_url = f"{SOURCE}{path}"
        try:
            r = requests.get(full_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            h = r.content.decode("utf-8", errors="replace")

            start_date, end_date = parse_dates_from_html(h)
            if not start_date:
                continue

            titulo = parse_title_from_html(h, slug)

            hora_m = re.search(r'"startDate"\s*:\s*"\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})', h)
            hora = hora_m.group(1) + " h" if hora_m else ""

            eventos.append({
                "slug":       slug,
                "titulo":     titulo,
                "start_date": start_date,
                "end_date":   end_date or start_date,
                "hora":       hora,
                "link":       full_url,
                "is_free":    1,
            })
            print(f"  [{start_date} - {end_date}] {titulo[:60]}")
        except Exception:
            continue

    return eventos


def import_mnba_scl():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando MNBA Chile (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Santiago de Chile", "Chile")

    place = {
        "name":             "Museo Nacional de Bellas Artes de Chile (MNBA)",
        "place_slug":       "mnba_scl",
        "category":         "Museo / Arte",
        "description":      "El museo de arte mas antiguo e importante de Chile (desde 1880). Edificio neoclasico en el Parque Forestal. Coleccion permanente de arte chileno y europeo. Exposiciones temporarias internacionales. Gratuito.",
        "opening_hours":    "Mar a dom: 10 a 18:45 h",
        "closed_days":      "Lunes",
        "price":            "Gratuito",
        "currency":         "CLP",
        "address":          "Parque Forestal s/n (Jose Miguel de la Barra 650), Santiago Centro",
        "contact":          "mnba.gob.cl | Tel: +56 2 2499-1600",
        "official_website": SOURCE,
        "source":           SOURCE,
        "last_verified":    today.isoformat(),
        "confidence_level": "high",
        "is_free":          1,
        "is_indoor":        1,
        "target_audience":  "todo publico",
        "has_own_agenda":   1,
    }
    insert_place(city_id, place)

    print("Scrapeando cartelera del MNBA Chile...")
    try:
        eventos = scrape_cartelera()
        print(f"  {len(eventos)} actividades encontradas")
    except Exception as e:
        print(f"  Error: {e}")
        eventos = []

    imported = 0
    skipped  = 0
    seen     = set()

    for ev in eventos:
        if ev["end_date"] < cutoff:
            skipped += 1
            continue

        key = f"{ev['slug']}_{ev['start_date']}"
        if key in seen:
            continue
        seen.add(key)

        status   = "scheduled" if ev["start_date"] >= today.isoformat() else "active"
        hora_str = ev["hora"] if ev.get("hora") else "Mar a dom 10-18:45 h"

        event = {
            "event_id":         f"mnba_scl_{ev['slug']}_{ev['start_date']}",
            "name":             ev["titulo"],
            "category":         "Museo / Exposicion",
            "venue":            VENUE,
            "start_date":       ev["start_date"],
            "end_date":         ev["end_date"],
            "time":             hora_str,
            "price":            f"Gratuito - ver programa: {ev['link']}",
            "ticket_source":    ev["link"],
            "official_source":  SOURCE,
            "status":           status,
            "confidence_level": "high",
            "is_free":          1,
            "is_indoor":        1,
            "target_audience":  "todo publico",
        }
        insert_event(city_id, event)
        imported += 1

    print(f"\nImportacion MNBA Chile completada: {imported} actividades ({skipped} anteriores omitidas)")


if __name__ == "__main__":
    import_mnba_scl()
