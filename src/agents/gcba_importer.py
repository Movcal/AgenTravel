"""
Importador de datos reales del GCBA (Gobierno de la Ciudad de Buenos Aires)
Fuente: https://data.buenosaires.gob.ar
"""
import csv
import io
import sys
import os
import requests
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

# URLs de datasets oficiales del GCBA
GCBA_SOURCES = {
    "eventos_masivos_2026": "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/agencia-gubernamental-de-control/permisos-eventos-masivos/permisos-eventos-masivos-2026.csv",
    "eventos_masivos_2025": "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/agencia-gubernamental-de-control/permisos-eventos-masivos/permisos-eventos-masivos-2025.csv",
}

def parse_fecha(fecha_str: str) -> str:
    """Convierte DD/M/YYYY a YYYY-MM-DD"""
    try:
        return datetime.strptime(fecha_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except:
        try:
            # Formato alternativo DD/M/YYYY HH:MM
            return datetime.strptime(fecha_str.strip().split()[0], "%d/%m/%Y").strftime("%Y-%m-%d")
        except:
            return fecha_str.strip()

def parse_hora(datetime_str: str) -> str:
    """Extrae la hora HH:MM de un string DD/M/YYYY HH:MM"""
    try:
        parts = datetime_str.strip().split()
        if len(parts) >= 2:
            return parts[1]
    except:
        pass
    return ""

def import_eventos_masivos(year: int = 2026):
    """Importa eventos masivos del GCBA a la base de datos."""
    url = GCBA_SOURCES.get(f"eventos_masivos_{year}")
    if not url:
        print(f"No hay URL para el año {year}")
        return

    print(f"\nDescargando eventos masivos {year} del GCBA...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    # El CSV del GCBA viene en UTF-8; decodificarlo como latin-1 corrompia
    # las eñes y acentos ('NUÑEZ' -> 'NUÃ‘EZ'). Fallback por si cambian.
    try:
        content = response.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = response.content.decode("latin-1")
    reader = csv.reader(io.StringIO(content), delimiter=";")

    init_db()
    city_id = get_or_create_city("Buenos Aires", "Argentina")

    # Solo importar eventos desde el primer dia del mes anterior
    from datetime import date as _date
    _today = _date.today()
    cutoff = _date(_today.year if _today.month > 1 else _today.year - 1,
                   _today.month - 1 if _today.month > 1 else 12, 1).strftime("%Y-%m-%d")
    print(f"  Filtrando eventos desde: {cutoff}")

    headers = None
    imported = 0
    skipped = 0

    for row in reader:
        if headers is None:
            # Limpiar BOM del header
            headers = [h.strip().strip("\ufeff").strip("\ufeff") for h in row]
            continue

        if len(row) < 4:
            continue

        try:
            # Columnas: FECHA, EVENTO, LUGAR, MODALIDAD, APERTURA, CIERRE, AFORO, BARRIO
            fecha_raw  = row[0].strip() if len(row) > 0 else ""
            nombre     = row[1].strip() if len(row) > 1 else ""
            lugar      = row[2].strip() if len(row) > 2 else ""
            modalidad  = row[3].strip() if len(row) > 3 else ""
            apertura   = row[4].strip() if len(row) > 4 else ""
            cierre     = row[5].strip() if len(row) > 5 else ""
            aforo      = row[6].strip() if len(row) > 6 else ""
            barrio     = row[7].strip() if len(row) > 7 else ""

            if not nombre or not fecha_raw:
                skipped += 1
                continue

            # Filtrar eventos anteriores al corte
            start_date_check = parse_fecha(fecha_raw)
            if start_date_check < cutoff:
                skipped += 1
                continue

            start_date = parse_fecha(fecha_raw)
            end_date   = parse_fecha(cierre.split()[0]) if cierre else start_date
            time_open  = parse_hora(apertura)
            time_close = parse_hora(cierre)
            horario    = f"{time_open} - {time_close}" if time_open and time_close else time_open

            # Determinar status segun fecha
            try:
                event_date = datetime.strptime(start_date, "%Y-%m-%d")
                today = datetime.today()
                if event_date < today:
                    status = "completed"
                else:
                    status = "scheduled"
            except:
                status = "scheduled"

            # Generar event_id unico
            event_id = f"gcba_{year}_{nombre[:20].replace(' ','_')}_{start_date}"

            event = {
                "event_id": event_id,
                "name": nombre,
                "category": modalidad,
                "venue": f"{lugar}, {barrio}" if barrio else lugar,
                "start_date": start_date,
                "end_date": end_date,
                "time": horario,
                "price": "Ver en sitio oficial",
                "ticket_source": "https://www.buenosaires.gob.ar",
                "official_source": "https://data.buenosaires.gob.ar - GCBA Permisos Eventos Masivos",
                "status": status,
                "confidence_level": "high",  # Fuente oficial del gobierno
            }

            insert_event(city_id, event)
            imported += 1

        except Exception as e:
            skipped += 1
            continue

    print(f"\nImportacion completada:")
    print(f"  Eventos importados: {imported}")
    print(f"  Eventos saltados:   {skipped}")
    print(f"  Fuente: GCBA - Permisos Eventos Masivos {year}")

if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    import_eventos_masivos(year)
