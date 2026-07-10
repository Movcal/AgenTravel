"""
Importador CCBB Rio de Janeiro (Centro Cultural Banco do Brasil).
Fuente: https://ccbb.com.br/rio-de-janeiro
Parsea la pagina principal para extraer eventos actuales con fechas.
"""
import sys, os, re, requests
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE  = "https://ccbb.com.br/rio-de-janeiro"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def parse_date_br(date_str: str, current_year: int) -> str:
    """Convierte DD/MM/YY a YYYY-MM-DD."""
    try:
        day, month, year_short = date_str.split("/")
        year = 2000 + int(year_short) if int(year_short) < 50 else 1900 + int(year_short)
        return f"{year}-{int(month):02d}-{int(day):02d}"
    except Exception:
        return ""


def guess_category(name: str, link: str) -> str:
    """Infiere categoria del evento por nombre/contexto."""
    nl = name.lower()
    if any(k in nl for k in ["festival", "cinema", "filme", "panorama", "cinemateca"]):
        return "Cinema / Festival"
    if any(k in nl for k in ["leitura", "livro", "literatura"]):
        return "Literatura / Clube de Leitura"
    if any(k in nl for k in ["samba", "música", "musica", "show", "concerto", "harp", "festival"]):
        return "Música / Show"
    if any(k in nl for k in ["exposição", "exposicao", "olho nu", "arte", "foto", "pintura"]):
        return "Arte / Exposição"
    if any(k in nl for k in ["teatro", "peça", "peca", "confuzo", "metamorfose", "veneno"]):
        return "Teatro / Espectáculo"
    if any(k in nl for k in ["história", "historia", "dinheiro", "banco", "integra", "povo"]):
        return "Exposição / Historia"
    return "Evento Cultural"


def fetch_events() -> list:
    """Scraping de la pagina principal del CCBB Rio."""
    try:
        resp = requests.get(SOURCE, headers=HEADERS, timeout=30, verify=False)
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Error accediendo a CCBB Rio: {e}")
        return []

    today_year = date.today().year
    events     = []
    seen_names = set()

    # --- Estrategia 1: h4 title + fecha en span siguiente ---
    for m in re.finditer(r'<h4[^>]*>(.*?)</h4>', html, re.S):
        raw_name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not raw_name or len(raw_name) < 3:
            continue
        # Palabras de navegacion a ignorar
        skip_words = {"resultados da busca", "bilheteria", "mão brasileira", "mao brasileira",
                      "confeitaria colombo", "belo horizonte", "brasília", "brasilia",
                      "rio de janeiro", "salvador", "são paulo", "sao paulo"}
        if raw_name.lower() in skip_words:
            continue

        # Buscar fecha dentro de 1000 chars siguientes
        after   = html[m.start(): m.start() + 1200]
        date_m  = re.search(r'(\d{2}/\d{2}/\d{2})\s+a\s+(\d{2}/\d{2}/\d{2})', after)
        if not date_m:
            continue

        start_iso = parse_date_br(date_m.group(1), today_year)
        end_iso   = parse_date_br(date_m.group(2), today_year)
        if not start_iso:
            continue

        # Link: buscar en 500 chars previos o posteriores
        ctx_before  = html[max(0, m.start() - 600): m.start()]
        link_m      = re.search(r'href="(https://ccbb\.com\.br/rio-de-janeiro/programacao/[^"]+)"', ctx_before)
        if not link_m:
            ctx_after = html[m.start(): m.start() + 600]
            link_m    = re.search(r'href="(https://ccbb\.com\.br/rio-de-janeiro/programacao/[^"]+)"', ctx_after)
        link = link_m.group(1) if link_m else SOURCE

        if raw_name in seen_names:
            continue
        seen_names.add(raw_name)

        events.append({
            "name":  raw_name,
            "start": start_iso,
            "end":   end_iso,
            "link":  link.rstrip("/"),
        })

    # --- Estrategia 2: meta description para eventos destacados (ej: Vik Muniz) ---
    meta_m = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
    if meta_m:
        meta_text = meta_m.group(1)
        # Patron: "Exposição Nombre: Subtitulo DD/MM/YY a DD/MM/YY"
        for featured in re.finditer(
            r'(?:Exposi[çc][aã]o|Teatro|Cinema|Evento)\s+([\wÀ-ÿ\s:!,\.\-\(\)]+?)\s+(\d{2}/\d{2}/\d{2})\s+a\s+(\d{2}/\d{2}/\d{2})',
            meta_text, re.I
        ):
            raw_name  = featured.group(1).strip().rstrip(",.")
            start_iso = parse_date_br(featured.group(2), today_year)
            end_iso   = parse_date_br(featured.group(3), today_year)
            if not start_iso or raw_name in seen_names:
                continue
            seen_names.add(raw_name)
            # Buscar link por nombre aproximado
            slug  = raw_name.lower().split(":")[0].strip().replace(" ", "-")
            slug  = re.sub(r"[^a-z0-9\-]", "", slug)[:40]
            link  = f"https://ccbb.com.br/rio-de-janeiro/programacao/{slug}/"
            events.append({
                "name":  raw_name,
                "start": start_iso,
                "end":   end_iso,
                "link":  link,
            })

    return events


def import_ccbb_rio():
    today = date.today()

    print("\nImportando CCBB Rio de Janeiro...")

    import warnings
    warnings.filterwarnings("ignore")

    init_db()
    city_id = get_or_create_city("Rio de Janeiro", "Brasil")

    # --- PLACE: CCBB Rio ---
    place = {
        "name": "Centro Cultural Banco do Brasil Rio (CCBB Rio)",
        "place_slug": "ccbb_rio",
        "category": "Centro Cultural / Arte y Espectáculos",
        "description": "Uno de los centros culturales más importantes de Brasil. Ofrece exposiciones de arte, teatro, cine, música y literatura. Sede en un edificio histórico del Centro do Rio (1906). Programación variada, muchos eventos gratuitos. Abierto de miércoles a lunes de 9h a 21h.",
        "opening_hours": "Miércoles a lunes: 9h - 21h (cerrado martes)",
        "closed_days": "Martes",
        "price": "La mayoría de exposiciones son gratuitas | Espectáculos desde R$20 (ver ccbb.com.br)",
        "currency": "BRL",
        "address": "Rua Primeiro de Março, 66 - Centro, Rio de Janeiro",
        "contact": "ccbb.com.br/rio-de-janeiro | +55 21 3808-2020",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 1,
        "is_indoor": 1,
        "target_audience": "todos",
        "has_own_agenda": 1,
    }
    insert_place(city_id, place)

    # --- Eventos ---
    events = fetch_events()
    print(f"  {len(events)} eventos encontrados")

    imported = skipped = 0
    cutoff   = today.isoformat()

    for ev in events:
        if ev["end"] < cutoff:
            skipped += 1
            continue

        category = guess_category(ev["name"], ev["link"])
        safe_id  = re.sub(r"[^a-z0-9]", "", ev["name"].lower())[:30]
        event_id = f"ccbb_rio_{ev['start']}_{safe_id}"

        event = {
            "event_id":         event_id,
            "name":             ev["name"],
            "category":         category,
            "venue":            "CCBB Rio - Rua Primeiro de Março, 66, Centro, Rio de Janeiro",
            "start_date":       ev["start"],
            "end_date":         ev["end"],
            "time":             "",
            "price":            "Gratuito o con cargo según actividad - ver ccbb.com.br/rio-de-janeiro",
            "ticket_source":    ev["link"],
            "official_source":  SOURCE,
            "status":           "scheduled" if ev["start"] >= cutoff else "active",
            "confidence_level": "high",
            "is_free": 1, "is_indoor": 1, "target_audience": "todos",
        }
        insert_event(city_id, event)
        imported += 1
        print(f"  [{ev['start']} - {ev['end']}] {ev['name'][:55]}")

    print(f"\nImportacion CCBB Rio completada: {imported} eventos ({skipped} ya pasados)")


if __name__ == "__main__":
    import_ccbb_rio()
