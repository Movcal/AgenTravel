"""
Importador del Teatro Municipal de Santiago.
Fuente: https://www.teatromunicipal.cl/wp-json/wp/v2/productions
El Teatro Municipal es el equivalente chileno del Teatro Colón:
ópera, ballet y orquesta filarmónica de Santiago.
"""
import sys, os, re, requests
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE    = "https://municipal.cl"
VENUE_MAP = {
    "teatro-municipal":   "Teatro Municipal de Santiago, San Antonio 149, Santiago Centro",
    "teatro-oriente":     "Teatro Oriente, Av. Pedro de Valdivia 099, Providencia, Santiago",
    "teatro-baquedano":   "Teatro Baquedano, Av. Italia 882, Santiago",
}
VENUE_DEFAULT = "Teatro Municipal de Santiago, San Antonio 149, Santiago Centro"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

MESES_ES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12
}


def clean_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def get_venue_from_classes(class_list: list) -> str:
    for cls in class_list:
        for key, address in VENUE_MAP.items():
            if key in cls:
                return address
    return VENUE_DEFAULT


def get_category_from_classes(class_list: list) -> str:
    for cls in class_list:
        if "production-category-" in cls:
            cat = cls.replace("production-category-", "").replace("-", " ").title()
            return f"Teatro / {cat}"
    return "Teatro / Espectáculo"


def fetch_productions(max_pages: int = 10) -> list:
    """WP API de shows/events — municipal.cl usa /wp/v2/shows y /wp/v2/ajde_events."""
    productions = []
    for endpoint in [
        f"{SOURCE}/wp-json/wp/v2/shows",
        f"{SOURCE}/wp-json/wp/v2/ajde_events",
        f"{SOURCE}/wp-json/wp/v2/posts",
    ]:
        page = 1
        while page <= max_pages:
            try:
                resp = requests.get(endpoint, params={
                    "per_page": 50, "page": page,
                    "_fields": "id,date,title,link,class_list,slug"
                }, headers=HEADERS, timeout=20)
                if resp.status_code == 400:
                    break
                if resp.status_code != 200:
                    break
                batch = resp.json()
                if not batch or not isinstance(batch, list):
                    break
                productions.extend(batch)
                total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                if page >= total_pages:
                    break
                page += 1
            except Exception:
                break
        if productions:
            print(f"  WP API encontrada: {endpoint} ({len(productions)} producciones)")
            return productions

    return productions


def scrape_funciones(url: str) -> list:
    """Extrae fechas/horas de funciones del HTML de la producción."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="replace")
    except Exception:
        return []

    current_year = date.today().year
    funciones = []

    # Patrón 1: "20/08, 20:00 hs" — igual que Teatro Colón
    for dia_mes, hora in re.findall(
        r'<span[^>]*>\w+</span>\s*(\d{1,2}/\d{2}),\s*(\d{2}:\d{2})\s*h', html
    ):
        try:
            dia, mes = dia_mes.split("/")
            d = date(current_year, int(mes), int(dia))
            if (date.today() - d).days > 30:
                d = date(current_year + 1, int(mes), int(dia))
            funciones.append({"date": d.isoformat(), "time": hora})
        except Exception:
            continue

    # Patrón 2: "sábado 20 de agosto, 20:00 h"
    if not funciones:
        for match in re.finditer(
            r'(?:lunes|martes|mi[ée]rcoles|jueves|viernes|s[aá]bado|domingo)\s+(\d{1,2})\s+de\s+(\w+)[\s,]+(\d{2}:\d{2})',
            html, re.I
        ):
            dia, mes_str, hora = match.group(1), match.group(2).lower(), match.group(3)
            mes = MESES_ES.get(mes_str)
            if not mes:
                continue
            try:
                d = date(current_year, mes, int(dia))
                if (date.today() - d).days > 30:
                    d = date(current_year + 1, mes, int(dia))
                funciones.append({"date": d.isoformat(), "time": hora})
            except Exception:
                continue

    # Patrón 3: datetime en meta tags o JSON-LD
    if not funciones:
        for dt in re.findall(r'"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', html):
            funciones.append({"date": dt[0], "time": dt[1]})

    # Patrón 4: "Martes 6 de octubre &#8211; 18:00 horas" (formato editorial de municipal.cl)
    if not funciones:
        for match in re.finditer(
            r'(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+'
            r'(\d{1,2})\s+de\s+(\w+)\s*(?:&#8211;|&#8212;|–|-)\s*(\d{2}:\d{2})',
            html, re.I
        ):
            dia, mes_str, hora = match.group(1), match.group(2).lower(), match.group(3)
            mes = MESES_ES.get(mes_str)
            if not mes:
                continue
            try:
                d = date(current_year, mes, int(dia))
                if (date.today() - d).days > 30:
                    d = date(current_year + 1, mes, int(dia))
                funciones.append({"date": d.isoformat(), "time": hora})
            except Exception:
                continue

    return funciones


def scrape_html_agenda() -> list:
    """Fallback: scraping directo de la agenda HTML del Teatro Municipal."""
    eventos = []
    try:
        resp = requests.get(f"{SOURCE}/agenda/", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Error agenda HTML: {e}")
        return []

    # Buscar links a producciones
    links = set(re.findall(
        r'href="(https://www\.teatromunicipal\.cl/[^"]*(?:obra|produccion|production|espectaculo)[^"]*)"',
        html, re.I
    ))
    if not links:
        links_rel = set(re.findall(r'href="(/[^"]*(?:obra|produccion|production|espectaculo)[^"]*)"', html, re.I))
        links = {f"{SOURCE}{l}" for l in links_rel}

    print(f"  Links encontrados en HTML: {len(links)}")

    current_year = date.today().year
    for url in sorted(links)[:30]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            h = r.content.decode("utf-8", errors="replace")
            titulo = re.search(r'<h1[^>]*>([^<]+)</h1>', h)
            titulo_txt = clean_html(titulo.group(1)) if titulo else url.split("/")[-2]

            fecha_m = re.search(r'(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?', h, re.I)
            if not fecha_m:
                continue
            mes = MESES_ES.get(fecha_m.group(2).lower())
            if not mes:
                continue
            anio = int(fecha_m.group(3)) if fecha_m.group(3) else current_year
            try:
                d = date(anio, mes, int(fecha_m.group(1)))
                eventos.append({"titulo": titulo_txt, "date": d.isoformat(), "time": "", "link": url})
            except Exception:
                continue
        except Exception:
            continue

    return eventos


def import_teatro_municipal_scl():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando Teatro Municipal de Santiago (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Santiago de Chile", "Chile")

    # --- PLACE: Teatro Municipal ---
    place = {
        "name": "Teatro Municipal de Santiago",
        "place_slug": "teatro_municipal_scl",
        "category": "Teatro / Ópera",
        "description": "El principal teatro lírico de Chile (desde 1857). Sede de la Orquesta Filarmónica de Santiago, el Ballet de Santiago y temporadas de ópera. El equivalente chileno del Teatro Colón de Buenos Aires.",
        "opening_hours": "Visitas guiadas: consultar teatromunicipal.cl | Funciones según temporada.",
        "closed_days": "Variable según temporada",
        "price": "Desde $5.000 CLP (visitas) / Funciones desde $8.000 CLP - ver teatromunicipal.cl",
        "currency": "CLP",
        "address": "San Antonio 149, Santiago Centro",
        "contact": "teatromunicipal.cl | Tel: +56 2 2463-8888",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "adultos",
        "has_own_agenda": 1,
        "place_slug": "teatro_municipal_scl",
    }
    insert_place(city_id, place)

    # --- Intentar WP API de producciones ---
    print("Buscando producciones via WP API...")
    productions = fetch_productions()

    imported = 0
    skipped  = 0

    if productions:
        for prod in productions:
            title = clean_html(prod.get("title", {}).get("rendered", ""))
            if not title:
                skipped += 1
                continue

            link       = prod.get("link", SOURCE)
            class_list = prod.get("class_list", [])
            prod_id    = prod.get("id")
            venue      = get_venue_from_classes(class_list)
            category   = get_category_from_classes(class_list)

            print(f"  [{prod_id}] {title[:60]}".encode('ascii', errors='replace').decode('ascii'))
            funciones = scrape_funciones(link)

            if not funciones:
                pub_date = prod.get("date", "")[:10]
                if pub_date < cutoff:
                    skipped += 1
                    continue
                event = {
                    "event_id":        f"tmscl_{prod_id}",
                    "name":            title,
                    "category":        category,
                    "venue":           venue,
                    "start_date":      pub_date,
                    "end_date":        pub_date,
                    "time":            "",
                    "price":           f"Con cargo - consultar precio: {link}",
                    "ticket_source":   link,
                    "official_source": SOURCE,
                    "status":          "scheduled" if pub_date >= today.isoformat() else "completed",
                    "confidence_level": "medium",
                    "is_free": 0, "is_indoor": 1, "target_audience": "adultos",
                }
                insert_event(city_id, event)
                imported += 1
            else:
                print(f"    {len(funciones)} funciones encontradas")
                for i, func in enumerate(funciones):
                    if func["date"] < cutoff:
                        continue
                    event = {
                        "event_id":        f"tmscl_{prod_id}_f{i+1}",
                        "name":            title,
                        "category":        category,
                        "venue":           venue,
                        "start_date":      func["date"],
                        "end_date":        func["date"],
                        "time":            func["time"],
                        "price":           f"Con cargo - consultar precio: {link}",
                        "ticket_source":   link,
                        "official_source": SOURCE,
                        "status":          "scheduled" if func["date"] >= today.isoformat() else "completed",
                        "confidence_level": "high",
                        "is_free": 0, "is_indoor": 1, "target_audience": "adultos",
                    }
                    insert_event(city_id, event)
                    imported += 1
    else:
        print("  WP API no disponible. Intentando scraping HTML...")
        eventos = scrape_html_agenda()
        for ev in eventos:
            if ev["date"] < cutoff:
                skipped += 1
                continue
            event = {
                "event_id":        f"tmscl_{ev['titulo'][:20].replace(' ','_')}_{ev['date']}",
                "name":            ev["titulo"],
                "category":        "Teatro / Espectáculo",
                "venue":           VENUE_DEFAULT,
                "start_date":      ev["date"],
                "end_date":        ev["date"],
                "time":            ev["time"],
                "price":           f"Con cargo - consultar precio: {ev['link']}",
                "ticket_source":   ev["link"],
                "official_source": SOURCE,
                "status":          "scheduled" if ev["date"] >= today.isoformat() else "completed",
                "confidence_level": "medium",
                "is_free": 0, "is_indoor": 1, "target_audience": "adultos",
            }
            insert_event(city_id, event)
            imported += 1

    print(f"\nImportacion Teatro Municipal completada: {imported} funciones ({skipped} omitidas)")


if __name__ == "__main__":
    import_teatro_municipal_scl()
