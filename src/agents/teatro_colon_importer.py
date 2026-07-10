"""
Importador de producciones del Teatro Colón.
Fuente: https://teatrocolon.org.ar/wp-json/wp/v2/productions
Cada producción puede tener N funciones (fechas individuales).
Cada función se importa como un evento independiente en la DB.
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

BASE_URL   = "https://teatrocolon.org.ar/wp-json/wp/v2/productions"
SITE_URL   = "https://teatrocolon.org.ar"
SOURCE     = "https://teatrocolon.org.ar"

# Mapa de venue por class_list
VENUE_MAP = {
    "places-teatro-colon":              "Teatro Colón, Cerrito 628, Buenos Aires",
    "places-teatro-presidente-alvear":  "Teatro Presidente Alvear, Av. Corrientes 1659, Buenos Aires",
    "places-teatro-coliseo":            "Teatro Coliseo, Marcelo T. de Alvear 1125, Buenos Aires",
}
VENUE_DEFAULT = "Teatro Colón, Cerrito 628, Buenos Aires"


def get_venue_from_classes(class_list: list) -> str:
    for cls in class_list:
        if cls in VENUE_MAP:
            return VENUE_MAP[cls]
    return VENUE_DEFAULT


def get_category_from_classes(class_list: list) -> str:
    for cls in class_list:
        if "production-category-" in cls:
            cat = cls.replace("production-category-", "").replace("-", " ").title()
            return f"Teatro / {cat}"
    return "Teatro / Espectáculo"


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_all_productions(max_pages: int = 10) -> list:
    productions = []
    page = 1
    while page <= max_pages:
        resp = requests.get(BASE_URL, params={
            "per_page": 50,
            "page": page,
            "_fields": "id,date,title,link,class_list,slug"
        }, headers=HEADERS, timeout=30)
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        productions.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return productions


def clean_title(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def scrape_funciones(url: str) -> list:
    """
    Scraping del HTML de la produccion.
    Retorna lista de dicts: {date: 'YYYY-MM-DD', time: 'HH:MM'}
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.content.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  [Error] No se pudo descargar {url}: {e}".encode('ascii','replace').decode())
        return []

    # Extraer año del contexto (buscar en <h4> tags de mes + año si existe, o usar año actual)
    year_match = re.search(r'(\d{4})', html[html.find('month-days'):html.find('month-days')+2000] if 'month-days' in html else '')
    current_year = date.today().year

    # Extraer funciones del span hide-desktop: "jueves 20/08, 20:00 hs"
    funciones_raw = re.findall(
        r'<span class="capitalize">\w+</span>\s*(\d{1,2}/\d{2}),\s*(\d{2}:\d{2}) hs',
        html
    )

    funciones = []
    for dia_mes, hora in funciones_raw:
        try:
            dia, mes = dia_mes.split('/')
            # Determinar año: si el mes ya pasó este año, es el siguiente
            d = date(current_year, int(mes), int(dia))
            if (date.today() - d).days > 30:
                d = date(current_year + 1, int(mes), int(dia))
            funciones.append({"date": d.isoformat(), "time": hora})
        except Exception:
            continue

    return funciones


def import_teatro_colon():
    # Solo importar eventos desde el primer dia del mes anterior
    from datetime import date
    today = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()
    print(f"\nDescargando producciones del Teatro Colon (desde {cutoff})...")
    productions = fetch_all_productions()
    print(f"Producciones encontradas: {len(productions)}")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # Registrar el Teatro Colón como place
    place = {
        "name": "Teatro Colón",
        "category": "Teatro / Opera",
        "description": "Uno de los mejores teatros de ópera del mundo. Sede de la Orquesta Filarmónica de Buenos Aires y el Ballet Estable.",
        "opening_hours": "Visitas guiadas: lunes a domingo 9 a 17 h. Funciones según temporada.",
        "closed_days": "Variable según temporada",
        "price": "Desde $10.000 (visitas) / Funciones desde $5.000",
        "currency": "ARS",
        "address": "Cerrito 628, Buenos Aires",
        "contact": "Tel: +54 11 4378-7100",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": date.today().isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "adultos",
        "has_own_agenda": 1,
        "place_slug": "teatro_colon",
    }
    insert_place(city_id, place)

    imported = 0
    skipped = 0
    today = date.today().isoformat()

    for prod in productions:
        title = clean_title(prod.get("title", {}).get("rendered", ""))
        if not title:
            skipped += 1
            continue

        link       = prod.get("link", "")
        class_list = prod.get("class_list", [])
        prod_id    = prod.get("id")
        venue      = get_venue_from_classes(class_list)
        category   = get_category_from_classes(class_list)

        print(f"\n  [{prod_id}] {title}".encode('ascii','replace').decode())
        funciones = scrape_funciones(link)

        if not funciones:
            # Sin funciones scrapeadas: importar como evento generico con fecha de publicacion
            pub_date = prod.get("date", "")[:10]
            event = {
                "event_id": f"colon_{prod_id}",
                "name": title,
                "category": category,
                "venue": venue,
                "start_date": pub_date,
                "end_date": pub_date,
                "time": "",
                "price": f"Con cargo - consultar precio: {link}",
                "ticket_source": link,
                "official_source": SOURCE,
                "status": "scheduled" if pub_date >= today else "completed",
                "confidence_level": "medium",
                "is_free": 0,
                "is_indoor": 1,
                "target_audience": "adultos",
            }
            insert_event(city_id, event)
            imported += 1
            skipped_funcs = 0
        else:
            # Una funcion = un evento independiente
            start_date = funciones[0]["date"]
            end_date   = funciones[-1]["date"]
            print(f"    {len(funciones)} funciones: {start_date} → {end_date}".encode('ascii','replace').decode())

            for i, func in enumerate(funciones):
                # Saltar funciones anteriores al corte
                if func["date"] < cutoff:
                    continue
                event_id = f"colon_{prod_id}_f{i+1}"
                status = "scheduled" if func["date"] >= today else "completed"
                event = {
                    "event_id": event_id,
                    "name": title,
                    "category": category,
                    "venue": venue,
                    "start_date": func["date"],
                    "end_date": func["date"],
                    "time": func["time"],
                    "price": f"Con cargo - consultar precio: {link}",
                    "ticket_source": link,
                    "official_source": SOURCE,
                    "status": status,
                    "confidence_level": "high",
                    "is_free": 0,
                    "is_indoor": 1,
                    "target_audience": "adultos",
                }
                insert_event(city_id, event)
                imported += 1

    print(f"\nImportacion completada: {imported} funciones del Teatro Colon ({skipped} producciones sin datos)")


if __name__ == "__main__":
    import_teatro_colon()
