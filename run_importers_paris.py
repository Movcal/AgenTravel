"""
Runner maestro para importar todos los datos de Paris.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_paris_importer import import_static_places_paris
from agents.agenda_paris_importer        import import_agenda_paris

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTRAVEL - Importacion Paris")
    print("=" * 60)

    import_static_places_paris()
    import_agenda_paris()

    print("\n" + "=" * 60)
    print("Importacion Paris completada.")
    print("=" * 60)
