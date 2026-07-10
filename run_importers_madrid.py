"""
Runner maestro para importar todos los datos de Madrid.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_madrid_importer import import_static_places_madrid
from agents.futbol_madrid_importer        import import_futbol_madrid
from agents.agenda_madrid_importer        import import_agenda_madrid

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTRAVEL - Importacion Madrid")
    print("=" * 60)

    import_static_places_madrid()
    import_futbol_madrid()
    import_agenda_madrid()

    print("\n" + "=" * 60)
    print("Importacion Madrid completada.")
    print("=" * 60)
