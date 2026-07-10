"""
Importador de La Bombonera (Boca Juniors).
- Museo de la Pasión Boquense: precios y horarios desde museoboquense.com
- Partidos en La Bombonera: desde el sitio oficial (no hay API pública de fixtures)
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE_MUSEO   = "https://museoboquense.com"
SOURCE_ESTADIO = "https://www.bocajuniors.com.ar"
VENUE_ESTADIO  = "La Bombonera - Estadio Alberto J. Armando, Brandsen 805, La Boca, Buenos Aires"
VENUE_MUSEO    = "Museo de la Pasión Boquense, Brandsen 805, La Boca, Buenos Aires"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def scrape_precios_museo() -> list:
    """Scraping de los tipos de visita y precios del museoboquense.com"""
    resp = requests.get(SOURCE_MUSEO, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("utf-8", errors="replace")

    pares = re.findall(
        r'<span>(Entrada al Museo[^<]+|Visita Express[^<]+)</span>.*?<span>\$ ([\d.]+)[^<]*</span>',
        html, re.DOTALL
    )
    return [(nombre.strip(), f"${precio} ARS") for nombre, precio in pares]


def import_bombonera():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando La Bombonera (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # --- PLACE: La Bombonera (estadio) ---
    place_estadio = {
        "name": "La Bombonera - Estadio Alberto J. Armando",
        "category": "Estadio / Icono Cultural",
        "description": "El estadio mas famoso de Argentina y uno de los mas reconocidos del mundo. Sede de Boca Juniors desde 1940. Visita obligada para cualquier turista en Buenos Aires.",
        "opening_hours": "Visitas guiadas: lunes a domingo 10 a 18 h (cierre boleterìa 17:30 h)",
        "closed_days": "Dias de partido (consultar antes de ir)",
        "price": "Desde $25.000 ARS (residentes) / Desde $37.000 ARS (extranjeros) - ver museoboquense.com",
        "currency": "ARS",
        "address": "Brandsen 805, La Boca, Buenos Aires",
        "contact": "Tel: +54 11 4362-1100 | museoboquense.com",
        "official_website": SOURCE_MUSEO,
        "source": SOURCE_MUSEO,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 0,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
        "place_slug": "estadio_bombonera",
    }
    insert_place(city_id, place_estadio)

    # --- PLACE: Museo de la Pasión Boquense ---
    place_museo = {
        "name": "Museo de la Pasión Boquense",
        "category": "Museo / Deportivo",
        "description": "Museo interactivo dentro de La Bombonera con la historia de Boca Juniors, trofeos, camisetas históricas y sala panorámica del estadio.",
        "opening_hours": "Lunes a domingo 10 a 18 h",
        "closed_days": "Dias de partido profesional",
        "price": "Desde $25.000 ARS (residentes adulto) / Desde $37.000 ARS (extranjeros) - incluye acceso al estadio",
        "currency": "ARS",
        "address": "Brandsen 805, La Boca, Buenos Aires",
        "contact": "museoboquense.com",
        "official_website": SOURCE_MUSEO,
        "source": SOURCE_MUSEO,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 0,
        "place_slug": "museo_pasion_boquense",
    }
    insert_place(city_id, place_museo)

    # --- EVENTS: Tipos de visita como eventos recurrentes ---
    print("\nScrapeando precios del museo...")
    try:
        precios = scrape_precios_museo()
        print(f"  {len(precios)} tipos de visita encontrados")
    except Exception as e:
        print(f"  Error scrapeando precios: {e}")
        precios = []

    # Consolidar precios en un solo string
    if precios:
        precio_str = " | ".join([f"{n}: {p}" for n, p in precios])
    else:
        precio_str = "Ver en museoboquense.com"

    # Evento genérico de visita guiada (recurrente, no tiene fecha fija)
    visita = {
        "event_id":        "boca_visita_guiada_2026",
        "name":            "Visita guiada: Museo + Estadio La Bombonera",
        "category":        "Turismo / Visita Guiada",
        "venue":           VENUE_ESTADIO,
        "start_date":      today.isoformat(),
        "end_date":        f"{today.year}-12-31",
        "time":            "Lunes a domingo 10:00 - 18:00 h (último ingreso 17:30 h)",
        "price":           f"Con cargo - {precio_str} - comprar en: {SOURCE_MUSEO}",
        "ticket_source":   SOURCE_MUSEO,
        "official_source": SOURCE_MUSEO,
        "status":          "active",
        "confidence_level": "high",
        "is_free":         0,
        "is_indoor":       0,
        "target_audience": "todo publico",
    }
    insert_event(city_id, visita)

    print("\nImportacion La Bombonera completada.")
    print("  NOTA: Los partidos de Boca no tienen API publica.")
    print(f"  Para ver fixture actualizado: {SOURCE_ESTADIO}")


if __name__ == "__main__":
    import_bombonera()
