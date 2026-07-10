"""
Importador del Complejo Teatral de Buenos Aires.
Incluye: Teatro San Martin, Teatro Regio, Teatro Sarmiento, Teatro Presidente Alvear.
Fuente: https://complejoteatral.gob.ar/agenda
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

BASE_URL = "https://complejoteatral.gob.ar/agenda"
SITE_URL = "https://complejoteatral.gob.ar"
SOURCE   = "https://complejoteatral.gob.ar"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# Venues del Complejo y sus direcciones
VENUE_MAP = {
    "teatro san martín":           "Teatro San Martín, Av. Corrientes 1530, Buenos Aires",
    "teatro san martin":           "Teatro San Martín, Av. Corrientes 1530, Buenos Aires",
    "sala martín coronado":        "Teatro San Martín - Sala Martín Coronado, Av. Corrientes 1530, Buenos Aires",
    "sala casacuberta":            "Teatro San Martín - Sala Casacuberta, Av. Corrientes 1530, Buenos Aires",
    "sala cunill cabanellas":      "Teatro San Martín - Sala Cunill Cabanellas, Av. Corrientes 1530, Buenos Aires",
    "sala leopoldo lugones":       "Teatro San Martín - Sala Leopoldo Lugones (Cine), Av. Corrientes 1530, Buenos Aires",
    "teatro regio":                "Teatro Regio, Av. Córdoba 6056, Buenos Aires",
    "teatro sarmiento":            "Teatro Sarmiento, Av. Sarmiento 2715, Buenos Aires",
    "teatro presidente alvear":    "Teatro Presidente Alvear, Av. Corrientes 1659, Buenos Aires",
    "centro cultural san martín":  "Centro Cultural San Martín, Sarmiento 1551, Buenos Aires",
}

def normalizar_venue(lugar_raw: str) -> str:
    lugar = lugar_raw.lower().strip()
    for key, address in VENUE_MAP.items():
        if key in lugar:
            return address
    return f"{lugar_raw.strip()}, Buenos Aires"


def parse_fecha_ct(numero: str, mes_str: str) -> str:
    """Convierte numero de dia + nombre de mes a YYYY-MM-DD."""
    mes = MESES.get(mes_str.lower().strip())
    if not mes:
        return ""
    anio = date.today().year
    try:
        d = date(anio, mes, int(numero))
        if (date.today() - d).days > 30:
            d = date(anio + 1, mes, int(numero))
        return d.isoformat()
    except Exception:
        return ""


def detect_is_free(lugar: str, titulo: str) -> int:
    t = (lugar + " " + titulo).lower()
    if "lugones" in t:
        return 0  # Cine Lugones tiene precio
    return 0  # Complejo Teatral tiene costo general (aunque accesible)


def detect_audience(titulo: str, categoria: str) -> str:
    t = (titulo + " " + categoria).lower()
    if "títere" in t or "titere" in t or "infan" in t or "niño" in t:
        return "familia"
    if "joven" in t or "adolesc" in t:
        return "jovenes"
    return "adultos"


def scrape_agenda() -> list:
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("utf-8", errors="replace")

    # Extraer items: data-slug + body
    pattern = r'<div class="small_item[^"]*"\s+data-slug="([^"]+)"[^>]*>(.*?)(?=<div class="small_item|<script\b|</body>)'
    items = re.findall(pattern, html, re.DOTALL)

    eventos = []
    for slug, body in items:
        titulo    = re.search(r'<h2[^>]*>([^<]+)</h2>', body)
        categoria = re.search(r'class="category[^"]*">([^<]+)</span>', body)
        lugar     = re.search(r'class="place">([^<]+)</span>', body)
        ribbon    = re.search(r'class="ribbon[^"]*">(.*?)</div>', body, re.DOTALL)

        titulo_txt    = titulo.group(1).strip() if titulo else slug
        categoria_txt = categoria.group(1).strip() if categoria else "teatro"
        lugar_txt     = lugar.group(1).strip() if lugar else ""
        ribbon_txt    = re.sub(r'<[^>]+>', ' ', ribbon.group(1)).strip() if ribbon else ""
        ribbon_clean  = re.sub(r'\s+', ' ', ribbon_txt).strip()

        # Parsear start y end date del ribbon
        # Ejemplos: "jueves 09 julio 23 agosto -"  o "A partir del martes 14 julio"
        numeros = re.findall(r'\b(\d{1,2})\b', ribbon_clean)
        meses_en   = re.findall(r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)', ribbon_clean.lower())

        start_date = ""
        end_date   = ""

        if len(numeros) >= 2 and len(meses_en) >= 2:
            # Rango: "09 julio ... 23 agosto"
            start_date = parse_fecha_ct(numeros[0], meses_en[0])
            end_date   = parse_fecha_ct(numeros[1], meses_en[1])
        elif len(numeros) >= 1 and len(meses_en) >= 1:
            start_date = parse_fecha_ct(numeros[0], meses_en[0])
            end_date   = start_date
        else:
            start_date = date.today().isoformat()
            end_date   = start_date

        if not end_date:
            end_date = start_date

        venue    = normalizar_venue(lugar_txt)
        is_free  = detect_is_free(lugar_txt, titulo_txt)
        audience = detect_audience(titulo_txt, categoria_txt)
        link     = f"{SITE_URL}/ver/{slug}"
        price    = f"Con cargo - consultar precio: {link}"

        eventos.append({
            "slug":        slug,
            "titulo":      titulo_txt,
            "categoria":   f"Teatro / {categoria_txt.title()}",
            "venue":       venue,
            "start_date":  start_date,
            "end_date":    end_date,
            "ribbon":      ribbon_clean[:100],
            "link":        link,
            "is_free":     is_free,
            "audience":    audience,
            "price":       price,
        })

    return eventos


def import_complejo_teatral():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nDescargando agenda del Complejo Teatral BA (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # Registrar venues como places
    venues_places = [
        {
            "name": "Teatro San Martín",
            "category": "Teatro / Centro Cultural",
            "description": "Principal teatro del Estado en Buenos Aires. Sede del Complejo Teatral BA con teatro, danza, cine y música.",
            "opening_hours": "Variable según función",
            "closed_days": "Lunes",
            "price": "Desde $3.000 (ver sitio oficial)",
            "currency": "ARS",
            "address": "Av. Corrientes 1530, Buenos Aires",
            "contact": "Tel: 0800-333-5254",
            "official_website": SOURCE,
            "source": SOURCE,
            "last_verified": today.isoformat(),
            "confidence_level": "high",
            "is_free": 0,
            "is_indoor": 1,
            "target_audience": "adultos",
            "has_own_agenda": 1,
            "place_slug": "teatro_san_martin",
        },
        {
            "name": "Teatro Regio",
            "category": "Teatro",
            "description": "Teatro del Complejo Teatral BA ubicado en el barrio de Coghlan.",
            "opening_hours": "Variable según función",
            "closed_days": "Variable",
            "price": "Ver sitio oficial",
            "currency": "ARS",
            "address": "Av. Córdoba 6056, Buenos Aires",
            "contact": "0800-333-5254",
            "official_website": SOURCE,
            "source": SOURCE,
            "last_verified": today.isoformat(),
            "confidence_level": "high",
            "is_free": 0,
            "is_indoor": 1,
            "target_audience": "adultos",
            "has_own_agenda": 1,
            "place_slug": "teatro_regio",
        },
        {
            "name": "Teatro Sarmiento",
            "category": "Teatro",
            "description": "Sala de teatro contemporáneo del Complejo Teatral BA en Palermo.",
            "opening_hours": "Variable según función",
            "closed_days": "Variable",
            "price": "Ver sitio oficial",
            "currency": "ARS",
            "address": "Av. Sarmiento 2715, Buenos Aires",
            "contact": "0800-333-5254",
            "official_website": SOURCE,
            "source": SOURCE,
            "last_verified": today.isoformat(),
            "confidence_level": "high",
            "is_free": 0,
            "is_indoor": 1,
            "target_audience": "adultos",
            "has_own_agenda": 1,
            "place_slug": "teatro_sarmiento",
        },
    ]
    for vp in venues_places:
        insert_place(city_id, vp)

    eventos = scrape_agenda()
    print(f"Obras en cartel: {len(eventos)}")

    imported = 0
    skipped  = 0

    for ev in eventos:
        if ev["end_date"] < cutoff:
            skipped += 1
            continue

        status = "scheduled" if ev["start_date"] >= today.isoformat() else "active"

        event = {
            "event_id":        f"ctba_{ev['slug']}",
            "name":            ev["titulo"],
            "category":        ev["categoria"],
            "venue":           ev["venue"],
            "start_date":      ev["start_date"],
            "end_date":        ev["end_date"],
            "time":            ev["ribbon"],
            "price":           ev["price"],
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

    print(f"\nImportacion completada: {imported} obras del Complejo Teatral ({skipped} anteriores a {cutoff} omitidas)")


if __name__ == "__main__":
    import_complejo_teatral()
