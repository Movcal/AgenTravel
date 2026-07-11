"""
Agente Guardian (Maintenance) - Agent 2
Mantiene la base de datos viva y confiable:
1. Archiva eventos pasados (end_date < hoy)
2. Limpia eventos viejos (end_date < 30 dias atras)
3. Refresca eventos por ciudad via importers

No tiene interaccion con usuarios. No crea ciudades nuevas.
Se ejecuta via scheduler.py (cron diario).
"""
import sys, os
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_connection, set_meta

# ── Buenos Aires ─────────────────────────────────────────────────────
from agents.gcba_importer              import import_eventos_masivos
from agents.teatro_colon_importer      import import_teatro_colon
from agents.bombonera_importer         import import_bombonera
from agents.monumental_importer        import import_monumental
from agents.mnba_importer              import import_mnba
from agents.malba_importer             import import_malba
from agents.complejo_teatral_importer  import import_complejo_teatral
from agents.cclm_importer              import import_cclm
from agents.gam_importer               import import_gam
from agents.palacio_libertad_importer  import import_palacio_libertad
from agents.planetario_importer        import import_planetario

# ── Santiago de Chile ─────────────────────────────────────────────────
from agents.futbol_scl_importer           import import_futbol_scl
from agents.teatro_municipal_scl_importer import import_teatro_municipal_scl
from agents.mnba_scl_importer             import import_mnba_scl

# ── Rio de Janeiro ────────────────────────────────────────────────────
from agents.futbol_rio_importer import import_futbol_rio
from agents.ccbb_rio_importer   import import_ccbb_rio
from agents.agenda_rio_importer import import_agenda_rio

# ── Madrid ────────────────────────────────────────────────────────────
from agents.futbol_madrid_importer import import_futbol_madrid
from agents.agenda_madrid_importer import import_agenda_madrid

# ── Paris ─────────────────────────────────────────────────────────────
from agents.agenda_paris_importer import import_agenda_paris

# ── New York City ─────────────────────────────────────────────────────
from agents.sports_nyc_importer import import_sports_nyc
from agents.events_nyc_importer import import_events_nyc


# Mapa: nombre de ciudad (en log) → lista de funciones a ejecutar
# Solo incluye importers de EVENTOS (dinamicos). Places son estaticos.
CITY_REFRESHERS = {
    "Buenos Aires": [
        lambda: import_eventos_masivos(year=date.today().year),
        import_teatro_colon,
        import_bombonera,
        import_monumental,
        import_mnba,
        import_malba,
        import_complejo_teatral,
        import_cclm,
        import_gam,
        import_palacio_libertad,
        import_planetario,
    ],
    "Santiago de Chile": [
        import_futbol_scl,
        import_teatro_municipal_scl,
        import_mnba_scl,
    ],
    "Rio de Janeiro": [
        import_futbol_rio,
        import_ccbb_rio,
        import_agenda_rio,
    ],
    "Madrid": [
        import_futbol_madrid,
        import_agenda_madrid,
    ],
    "Paris": [
        import_agenda_paris,
    ],
    "New York City": [
        import_sports_nyc,
        import_events_nyc,
    ],
}


# ─────────────────────────────────────────────────────────────────────
# Tareas de mantenimiento de DB
# ─────────────────────────────────────────────────────────────────────

def archive_past_events() -> int:
    """Marca como 'completed' eventos cuya end_date ya paso."""
    today = date.today().isoformat()
    conn  = get_connection()
    cur   = conn.execute(
        "UPDATE events SET status='completed' WHERE end_date < ? AND status IN ('scheduled','active')",
        (today,)
    )
    conn.commit()
    print(f"  [Guardian] {cur.rowcount} eventos marcados como completados")
    return cur.rowcount


def cleanup_old_events(days: int = 30) -> int:
    """Archiva eventos que terminaron hace mas de N dias."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn   = get_connection()
    cur    = conn.execute(
        "UPDATE events SET status='archived' WHERE end_date < ? AND status IN ('scheduled','active','completed')",
        (cutoff,)
    )
    conn.commit()
    print(f"  [Guardian] {cur.rowcount} eventos archivados (terminaron hace >{days} dias)")
    return cur.rowcount


def db_stats() -> dict:
    """Devuelve estadisticas actuales de la DB."""
    today = date.today().isoformat()
    conn  = get_connection()
    cities = conn.execute("SELECT id, name FROM cities").fetchall()
    stats = {}
    for city_id, city_name in cities:
        places = conn.execute(
            "SELECT COUNT(*) FROM places WHERE city_id=?", (city_id,)
        ).fetchone()[0]
        upcoming = conn.execute(
            "SELECT COUNT(*) FROM events WHERE city_id=? AND end_date >= ? AND status != 'archived'",
            (city_id, today)
        ).fetchone()[0]
        stats[city_name] = {"places": places, "upcoming_events": upcoming}
    return stats


# ─────────────────────────────────────────────────────────────────────
# Refresh por ciudad
# ─────────────────────────────────────────────────────────────────────

def refresh_city(city_label: str) -> None:
    """Re-ejecuta todos los importers de eventos de una ciudad."""
    importers = CITY_REFRESHERS.get(city_label)
    if not importers:
        print(f"  [Guardian] Ciudad no reconocida: {city_label}")
        return

    print(f"\n  [Guardian] Refrescando eventos: {city_label}")
    for fn in importers:
        name = getattr(fn, "__name__", "lambda")
        try:
            fn()
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")


def refresh_all_cities() -> None:
    """Refresca todas las ciudades."""
    for city_label in CITY_REFRESHERS:
        refresh_city(city_label)


# ─────────────────────────────────────────────────────────────────────
# Entry point principal
# ─────────────────────────────────────────────────────────────────────

def run_guardian(refresh: bool = True, cities: list = None) -> None:
    """
    Ciclo completo del Guardian.
    refresh: si True, re-ejecuta importers de eventos.
    cities:  lista de ciudades a refrescar. None = todas.
    """
    now = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"  GUARDIAN - Mantenimiento {now}")
    print(f"{'='*60}")

    init_db()

    # 1. Estadisticas antes
    print("\n[1] Estado actual de la DB:")
    stats_before = db_stats()
    for city, s in stats_before.items():
        print(f"    {city}: {s['places']} lugares, {s['upcoming_events']} eventos futuros")

    # 2. Archivar eventos pasados
    print("\n[2] Archivando eventos pasados...")
    archive_past_events()
    cleanup_old_events(days=30)

    # 3. Refrescar eventos
    if refresh:
        print("\n[3] Refrescando datos de eventos...")
        if cities:
            for city in cities:
                refresh_city(city)
        else:
            refresh_all_cities()

    # 4. Estadisticas despues
    print("\n[4] Estado final de la DB:")
    stats_after = db_stats()
    for city, s in stats_after.items():
        print(f"    {city}: {s['places']} lugares, {s['upcoming_events']} eventos futuros")

    # Registrar la corrida: /ask lo expone como "last_data_refresh" en el
    # comprobante de investigacion (prueba de que los datos estan vivos).
    set_meta("last_guardian_run", datetime.now().isoformat(timespec="seconds"))

    print(f"\n{'='*60}")
    print(f"  GUARDIAN completado: {now}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgenTravel Guardian - Mantenimiento de DB")
    parser.add_argument("--no-refresh", action="store_true", help="Solo archivar, sin refrescar importers")
    parser.add_argument("--city", nargs="+", help="Ciudades especificas a refrescar (ej: Madrid Paris)")
    args = parser.parse_args()

    run_guardian(
        refresh=not args.no_refresh,
        cities=args.city,
    )
