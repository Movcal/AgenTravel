"""
Runner maestro para importar todos los datos de Buenos Aires.
"""
import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agents.static_places_bsas_importer import import_static_places_bsas
from agents.gcba_importer               import import_eventos_masivos
from agents.teatro_colon_importer       import import_teatro_colon
from agents.bombonera_importer          import import_bombonera
from agents.monumental_importer         import import_monumental
from agents.mnba_importer               import import_mnba
from agents.malba_importer              import import_malba
from agents.complejo_teatral_importer   import import_complejo_teatral
from agents.cclm_importer              import import_cclm
from agents.gam_importer               import import_gam
from agents.palacio_libertad_importer  import import_palacio_libertad
from agents.planetario_importer        import import_planetario

if __name__ == "__main__":
    print("=" * 60)
    print("AGENTRAVEL - Importacion Buenos Aires")
    print("=" * 60)

    import_static_places_bsas()
    import_eventos_masivos(year=date.today().year)
    import_teatro_colon()
    import_bombonera()
    import_monumental()
    import_mnba()
    import_malba()
    import_complejo_teatral()
    import_cclm()
    import_gam()
    import_palacio_libertad()
    import_planetario()

    print("\n" + "=" * 60)
    print("Importacion Buenos Aires completada.")
    print("=" * 60)
