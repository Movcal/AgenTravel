"""
Importador de eventos del Palacio Libertad (ex CCK)
Fuente: https://palaciolibertad.gob.ar/wp-json/wp/v2/mec-events
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

BASE_URL = "https://palaciolibertad.gob.ar/wp-json/wp/v2/mec-events"
VENUE = "Palacio Libertad (ex CCK), Sarmiento 151, Buenos Aires"
SOURCE = "https://palaciolibertad.gob.ar"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

def clean_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()

def detect_is_free(text: str) -> int:
    """Retorna 1 si el evento es gratuito, 0 si es pago, None si no se puede determinar."""
    t = text.lower()
    free_keywords = [
        "ingreso libre", "entrada libre", "ingreso gratuito", "entrada gratuita",
        "gratuito", "gratuita", "gratis", "sin cargo", "libre y gratuito",
        "libre de costo", "acceso libre", "acceso gratuito", "entrada sin cargo",
        "ingreso sin cargo", "free"
    ]
    paid_keywords = [
        "entradas en venta", "compra tu entrada", "tickets", "precio:", "$ ",
        "adquiri", "venta de entradas", "reserva tu entrada"
    ]
    for kw in free_keywords:
        if kw in t:
            return 1
    for kw in paid_keywords:
        if kw in t:
            return 0
    return None

def detect_is_indoor(text: str, title: str = "") -> int:
    """Retorna 1 si es bajo techo, 0 si es al aire libre, None si no se puede determinar."""
    t = (text + " " + title).lower()
    indoor_keywords = [
        "sala", "teatro", "auditorio", "foyer", "galeria", "galería",
        "biblioteca", "salon", "salón", "espacio", "estudio"
    ]
    outdoor_keywords = [
        "plaza seca", "explanada", "terraza", "parque", "patio exterior",
        "al aire libre", "exterior", "jardin", "jardín"
    ]
    for kw in outdoor_keywords:
        if kw in t:
            return 0
    for kw in indoor_keywords:
        if kw in t:
            return 1
    return None

def detect_target_audience(text: str, title: str = "") -> str:
    """Detecta el publico objetivo del evento."""
    t = (text + " " + title).lower()
    if any(k in t for k in ["niños", "infantil", "para chicos", "para ninos", "ninos"]):
        if any(k in t for k in ["familia", "familiar", "adultos"]):
            return "familia"
        return "infantil"
    if any(k in t for k in ["familia", "familiar", "todas las edades", "toda la familia"]):
        return "familia"
    if any(k in t for k in ["adultos mayores", "tercera edad", "seniors"]):
        return "adultos mayores"
    if any(k in t for k in ["jovenes", "jóvenes", "adolescentes"]):
        return "jovenes"
    if any(k in t for k in ["profesionales", "academico", "académico", "universitario"]):
        return "adultos"
    return "todo publico"

def parse_dates_from_text(text: str, pub_date: str) -> tuple:
    """
    Extrae start_date y end_date del texto en español del excerpt.
    Ejemplos:
      "Sabado 1 de agosto, 17 h"         -> 2026-08-01
      "Viernes 18 y miercoles 30 de abril" -> start=2026-04-18, end=2026-04-30
      "Del 15 al 28 de julio"             -> start=2026-07-15, end=2026-07-28
    Fallback: usa pub_date si no puede parsear.
    """
    text_lower = text.lower()
    today = date.today()
    ref_year = today.year

    found_dates = []

    dias_semana = r'(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)'
    # Patron: "N y N de mes", "N y lunes N de mes", "del N al N de mes"
    patron_rango = r'(?:del?\s+)?(\d{1,2})(?:\s*(?:,|y|al)\s*' + dias_semana + r'?\s*\d{1,2})*\s*(?:,|y|al)\s*' + dias_semana + r'?\s*(\d{1,2})\s+de\s+(' + '|'.join(MESES.keys()) + r')'
    m = re.search(patron_rango, text_lower)
    if m:
        dia_ini = int(m.group(1))
        dia_fin = int(m.group(2))
        mes = MESES[m.group(3)]
        try:
            d_ini = date(ref_year, mes, dia_ini)
            if (today - d_ini).days > 365:
                d_ini = date(ref_year + 1, mes, dia_ini)
            d_fin = date(d_ini.year, mes, dia_fin)
            return d_ini.isoformat(), d_fin.isoformat()
        except:
            pass

    # Patron simple: "N de mes" (puede aparecer varias veces)
    patron_simple = r'(\d{1,2})\s+de\s+(' + '|'.join(MESES.keys()) + r')'
    matches = re.findall(patron_simple, text_lower)
    for dia_str, mes_str in matches:
        try:
            mes = MESES[mes_str]
            dia = int(dia_str)
            d = date(ref_year, mes, dia)
            # Si la fecha es muy antigua (mas de 6 meses atras), probar año siguiente
            if (today - d).days > 180:
                d = date(ref_year + 1, mes, dia)
            found_dates.append(d)
        except:
            continue

    if found_dates:
        found_dates.sort()
        return found_dates[0].isoformat(), found_dates[-1].isoformat()

    # Fallback: usar fecha de publicacion
    return pub_date, pub_date

def fetch_all_events(max_pages: int = 10) -> list:
    events = []
    page = 1
    while page <= max_pages:
        resp = requests.get(BASE_URL, params={
            "per_page": 100,
            "page": page,
            "_fields": "id,date,title,excerpt,link,mec_category"
        }, timeout=30)
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        events.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return events

def parse_event(raw: dict) -> dict:
    title = clean_html(raw.get("title", {}).get("rendered", ""))
    excerpt = clean_html(raw.get("excerpt", {}).get("rendered", ""))
    pub_date = raw.get("date", "")[:10]
    link = raw.get("link", "")
    event_id = f"palacio_libertad_{raw.get('id')}"

    start_date, end_date = parse_dates_from_text(excerpt, pub_date)

    today = date.today().isoformat()
    status = "scheduled" if start_date >= today else "completed"

    # Palacio Libertad es centro cultural estatal: los eventos son gratuitos por defecto.
    # Solo se marca como pago si el texto indica explicitamente costo.
    is_free_detected = detect_is_free(excerpt)
    is_free = is_free_detected if is_free_detected == 0 else 1
    is_indoor = detect_is_indoor(excerpt, title)
    target_audience = detect_target_audience(excerpt, title)

    price = "Gratuito" if is_free else "Con cargo (ver sitio oficial)"

    return {
        "event_id": event_id,
        "name": title,
        "category": "Cultural / Palacio Libertad",
        "venue": VENUE,
        "start_date": start_date,
        "end_date": end_date,
        "time": excerpt[:200] if excerpt else "",
        "price": price,
        "ticket_source": link,
        "official_source": SOURCE,
        "status": status,
        "confidence_level": "high",
        "is_free": is_free,
        "is_indoor": is_indoor,
        "target_audience": target_audience,
    }

def import_palacio_libertad():
    today = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()
    print(f"\nDescargando eventos de Palacio Libertad (desde {cutoff})...")
    raw_events = fetch_all_events()
    print(f"Eventos encontrados en API: {len(raw_events)}")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    imported = 0
    skipped = 0
    for raw in raw_events:
        event = parse_event(raw)
        if event["name"]:
            if event["end_date"] < cutoff:
                skipped += 1
                continue
            insert_event(city_id, event)
            imported += 1

    print(f"\nImportacion completada: {imported} eventos del Palacio Libertad ({skipped} anteriores a {cutoff} omitidos)")

if __name__ == "__main__":
    import_palacio_libertad()
