"""
Runner maestro para importar todos los datos de Rio de Janeiro.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_rio_importer import import_static_places_rio
from agents.futbol_rio_importer         import import_futbol_rio
from agents.ccbb_rio_importer           import import_ccbb_rio

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTRAVEL - Importacion Rio de Janeiro")
    print("=" * 60)

    import_static_places_rio()
    import_futbol_rio()
    import_ccbb_rio()

    print("\n" + "=" * 60)
    print("Importacion Rio de Janeiro completada.")
    print("=" * 60)
