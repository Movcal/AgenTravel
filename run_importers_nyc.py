"""
Runner maestro para importar todos los datos de New York City.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_nyc_importer import import_static_places_nyc
from agents.sports_nyc_importer        import import_sports_nyc
from agents.events_nyc_importer        import import_events_nyc

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTRAVEL - Importacion New York City")
    print("=" * 60)

    import_static_places_nyc()
    import_sports_nyc()
    import_events_nyc()

    print("\n" + "=" * 60)
    print("Importacion New York City completada.")
    print("=" * 60)
