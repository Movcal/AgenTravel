"""
Runner maestro para importar todos los datos de Santiago de Chile.
Ejecuta los importers en orden, desde los estaticos hasta los dinamicos.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_scl_importer import import_static_places_scl
from agents.gam_importer               import import_gam
from agents.teatro_municipal_scl_importer import import_teatro_municipal_scl
from agents.mnba_scl_importer          import import_mnba_scl
from agents.cclm_importer              import import_cclm
from agents.futbol_scl_importer        import import_futbol_scl

from db.database import get_connection
from datetime import date

def run_all():
    print("\n" + "="*60)
    print("  IMPORTACION COMPLETA - Santiago de Chile")
    print("="*60)

    print("\n[1/6] Lugares estaticos (monumentos, parques, mercados...)")
    import_static_places_scl()

    print("\n[2/6] GAM - Centro Cultural Gabriela Mistral")
    import_gam()

    print("\n[3/6] Teatro Municipal de Santiago")
    import_teatro_municipal_scl()

    print("\n[4/6] MNBA Chile - Museo Nacional de Bellas Artes")
    import_mnba_scl()

    print("\n[5/6] CCLM - Centro Cultural La Moneda")
    import_cclm()

    print("\n[6/6] Futbol - Primera Division + Copa Chile")
    import_futbol_scl()

    # Resumen final
    conn = get_connection()
    city_id = conn.execute("SELECT id FROM cities WHERE name='Santiago de Chile'").fetchone()
    if city_id:
        places = conn.execute("SELECT COUNT(*) FROM places WHERE city_id=?", (city_id[0],)).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events WHERE city_id=?", (city_id[0],)).fetchone()[0]
        upcoming = conn.execute(
            "SELECT COUNT(*) FROM events WHERE city_id=? AND end_date >= ?",
            (city_id[0], date.today().isoformat())
        ).fetchone()[0]

    print("\n" + "="*60)
    print("  RESUMEN FINAL - Santiago de Chile")
    print("="*60)
    print(f"  Lugares:            {places}")
    print(f"  Eventos totales:    {events}")
    print(f"  Eventos proximos:   {upcoming}")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_all()
