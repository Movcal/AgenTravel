"""
Importador del Planetario Galileo Galilei de Buenos Aires.
Fuente: https://planetario.buenosaires.gob.ar/agenda
El Planetario publica su agenda mensual en HTML con shows del domo,
visitas guiadas y actividades con horarios y público recomendado.
"""
import sys, os, re, requests
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

SOURCE = "https://planetario.buenosaires.gob.ar"
VENUE  = "Planetario Galileo Galilei, Av. Sarmiento y Belisario Roldán, Palermo, Buenos Aires"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# Audiencia según palabras clave en el texto del espectáculo
AUDIENCE_MAP = [
    (["adultos y adolescentes", "adultos"], "adultos"),
    (["niños pequeños", "ninos pequenos", "bebes"], "infantil"),
    (["niños", "ninos", "chicos"], "familia"),
    (["adolescentes", "jovenes", "jóvenes"], "jovenes"),
]


def detect_audience(texto: str) -> str:
    t = texto.lower()
    for kws, audience in AUDIENCE_MAP:
        if any(k in t for k in kws):
            return audience
    return "todo publico"


def parse_rango_fechas(texto: str) -> tuple:
    """
    Parsea rangos como:
    - "9 al 12 de julio"
    - "del sábado 18 de julio al domingo 2 de agosto"
    - "martes 14 al viernes 17 de julio"
    - "sábado 25, viernes 31 de julio y sábado 1 de agosto"
    Retorna (start_date, end_date) en ISO format.
    """
    t = texto.lower()
    anio = date.today().year

    # Patrón: "del/desde N al M de MES" o "N al M de MES"
    m = re.search(
        r'(?:del?\s+)?(?:\w+\s+)?(\d{1,2})\s+(?:de\s+)?(?:' + '|'.join(MESES.keys()) + r')?\s*al?\s+(?:\w+\s+)?(\d{1,2})\s+de\s+(' + '|'.join(MESES.keys()) + r')',
        t
    )
    if m:
        dia_ini = int(m.group(1))
        dia_fin = int(m.group(2))
        mes_str = m.group(3)
        mes = MESES.get(mes_str, date.today().month)
        try:
            d_ini = date(anio, mes, dia_ini)
            d_fin = date(anio, mes, dia_fin)
            if (date.today() - d_ini).days > 60:
                d_ini = date(anio + 1, mes, dia_ini)
                d_fin = date(anio + 1, mes, dia_fin)
            return d_ini.isoformat(), d_fin.isoformat()
        except Exception:
            pass

    # Patrón: "N de MES al M de MES2"
    m2 = re.search(
        r'(\d{1,2})\s+de\s+(' + '|'.join(MESES.keys()) + r')\s+al?\s+(\d{1,2})\s+de\s+(' + '|'.join(MESES.keys()) + r')',
        t
    )
    if m2:
        try:
            d_ini = date(anio, MESES[m2.group(2)], int(m2.group(1)))
            d_fin = date(anio, MESES[m2.group(4)], int(m2.group(3)))
            if d_fin < d_ini:
                d_fin = date(anio + 1, MESES[m2.group(4)], int(m2.group(3)))
            if (date.today() - d_ini).days > 60:
                d_ini = date(anio + 1, MESES[m2.group(2)], int(m2.group(1)))
                d_fin = date(anio + 1, MESES[m2.group(4)], int(m2.group(3)))
            return d_ini.isoformat(), d_fin.isoformat()
        except Exception:
            pass

    return "", ""


def scrape_agenda() -> list:
    """
    Scraping de la agenda del Planetario.
    Estructura del HTML:
      <h3>Actividades mes de julio</h3>
      <p><strong>FINDE XXL (9 al 12 de julio)</strong></p>
      <h5>Funciones Inmersivas</h5>
      <p>12.00 h  Agujeros Negros (recomendado para adultos) ...</p>
    """
    resp = requests.get(f"{SOURCE}/agenda", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.content.decode("utf-8", errors="replace")

    # Extraer el bloque de contenido
    idx = html.find("Actividades mes")
    if idx < 0:
        return []
    contenido = html[idx:]

    # Limpiar HTML básico
    texto = re.sub(r'<br\s*/?>', '\n', contenido)
    texto = re.sub(r'<[^>]+>', ' ', texto)
    texto = re.sub(r'&nbsp;', ' ', texto)
    texto = re.sub(r'&#\d+;', ' ', texto)
    texto = re.sub(r'&[a-z]+;', ' ', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n\s*\n', '\n', texto)

    eventos = []
    current_rango = ("", "")

    for linea in texto.split('\n'):
        linea = linea.strip()
        if not linea:
            continue

        # Detectar rango de fechas en headers: "FINDE XXL (9 al 12 de julio)"
        # o "Desde el sábado 18 de julio al domingo 2 de agosto"
        if re.search(r'\d{1,2}.*(?:al|hasta).*(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)', linea, re.I):
            rango = parse_rango_fechas(linea)
            if rango[0]:
                current_rango = rango

        # Detectar show: "12.00 h  Agujeros Negros (recomendado para adultos)"
        m_show = re.match(r'(\d{1,2})[.:h](\d{0,2})\s*h\s+(.+)', linea, re.I)
        if m_show and current_rango[0]:
            hora_h = m_show.group(1)
            hora_m = m_show.group(2) or "00"
            hora_str = f"{hora_h.zfill(2)}:{hora_m.zfill(2)}"
            descripcion = m_show.group(3).strip()

            # Nombre del show (antes del paréntesis)
            nombre_m = re.match(r'([^(]+)', descripcion)
            nombre = nombre_m.group(1).strip() if nombre_m else descripcion[:50]
            # Limpiar emojis y caracteres especiales del nombre
            nombre = re.sub(r'[^\w\s\-.,:()/áéíóúüñÁÉÍÓÚÜÑ]', '', nombre).strip()

            audience = detect_audience(descripcion)

            if current_rango[0]:
                evento = {
                    "nombre":     nombre,
                    "descripcion": descripcion[:200],
                    "start_date": current_rango[0],
                    "end_date":   current_rango[1],
                    "hora":       hora_str,
                    "audience":   audience,
                }
                eventos.append(evento)

    return eventos


def import_planetario():
    today  = date.today()
    cutoff = date(today.year if today.month > 1 else today.year - 1,
                  today.month - 1 if today.month > 1 else 12, 1).isoformat()

    print(f"\nImportando Planetario Galileo Galilei (desde {cutoff})...")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # --- PLACE: Planetario ---
    place = {
        "name": "Planetario Galileo Galilei",
        "category": "Ciencia / Astronomía",
        "description": "El planetario más importante de Argentina. Shows inmersivos full dome, museo astronómico, observación por telescopios y visitas guiadas.",
        "opening_hours": "Mar a vie: 9 a 18 h | Sab y dom: 10 a 20 h (shows desde las 11 h)",
        "closed_days": "Lunes",
        "price": "Shows desde $5.000 ARS - ver planetario.buenosaires.gob.ar/tickets",
        "currency": "ARS",
        "address": "Av. Sarmiento y Belisario Roldán, Palermo, Buenos Aires",
        "contact": "planetario.buenosaires.gob.ar",
        "official_website": SOURCE,
        "source": SOURCE,
        "last_verified": today.isoformat(),
        "confidence_level": "high",
        "is_free": 0,
        "is_indoor": 1,
        "target_audience": "todo publico",
        "has_own_agenda": 1,
        "place_slug": "planetario_galileo_galilei",
    }
    insert_place(city_id, place)

    # --- Scraping de shows ---
    print("Scrapeando agenda del Planetario...")
    try:
        shows = scrape_agenda()
        print(f"  {len(shows)} funciones encontradas")
    except Exception as e:
        print(f"  Error: {e}")
        shows = []

    imported = 0
    skipped  = 0
    seen     = set()

    for show in shows:
        if show["end_date"] < cutoff:
            skipped += 1
            continue

        key = f"{show['nombre']}_{show['start_date']}_{show['hora']}"
        if key in seen:
            continue
        seen.add(key)

        status = "scheduled" if show["start_date"] >= today.isoformat() else "active"
        slug   = re.sub(r'[^a-z0-9]+', '_', show["nombre"].lower())[:30]

        event = {
            "event_id":        f"planetario_{slug}_{show['start_date']}_{show['hora'].replace(':','')}",
            "name":            show["nombre"],
            "category":        "Ciencia / Show Astronómico",
            "venue":           VENUE,
            "start_date":      show["start_date"],
            "end_date":        show["end_date"],
            "time":            f"{show['hora']} h",
            "price":           f"Con cargo - consultar precio: {SOURCE}/tickets",
            "ticket_source":   f"{SOURCE}/tickets",
            "official_source": SOURCE,
            "status":          status,
            "confidence_level": "high",
            "is_free":         0,
            "is_indoor":       1,
            "target_audience": show["audience"],
        }
        insert_event(city_id, event)
        imported += 1

    print(f"\nImportacion Planetario completada: {imported} funciones ({skipped} omitidas)")


if __name__ == "__main__":
    import_planetario()
