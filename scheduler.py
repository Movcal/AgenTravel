"""
Scheduler de AgenTravel - Orquestador del Guardian.
Ejecuta el Guardian diariamente a la hora configurada.

Uso:
  python scheduler.py                  # corre cada dia a las 03:00 AM
  python scheduler.py --hour 6         # corre a las 06:00 AM
  python scheduler.py --once           # corre una vez ahora y sale
  python scheduler.py --once --city Madrid Paris   # refresca solo esas ciudades
"""
import sys, os, time, argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from agents.guardian import run_guardian


def next_run_seconds(target_hour: int) -> float:
    """Segundos hasta la proxima ejecucion a target_hour:00."""
    now   = datetime.now()
    today = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if now >= today:
        from datetime import timedelta
        today += timedelta(days=1)
    return (today - now).total_seconds()


def run_scheduler(hour: int = 3, cities: list = None) -> None:
    """Bucle principal: ejecuta Guardian una vez al dia a la hora indicada."""
    print(f"[Scheduler] Iniciado. Guardian correra diariamente a las {hour:02d}:00.")
    print(f"[Scheduler] Ciudades: {'todas' if not cities else ', '.join(cities)}")
    print("[Scheduler] Ctrl+C para detener.\n")

    while True:
        wait = next_run_seconds(hour)
        next_time = datetime.now().replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        if datetime.now().hour >= hour:
            next_time += timedelta(days=1)

        print(f"[Scheduler] Proxima ejecucion: {next_time.strftime('%Y-%m-%d %H:%M')} "
              f"(en {wait/3600:.1f} horas)")

        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\n[Scheduler] Detenido por el usuario.")
            sys.exit(0)

        try:
            run_guardian(refresh=True, cities=cities)
        except Exception as e:
            print(f"[Scheduler] ERROR en Guardian: {e}")

        # Esperar 60s para no re-ejecutar en el mismo minuto
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgenTravel Scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecutar Guardian una vez ahora y salir"
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=3,
        help="Hora del dia para ejecucion diaria (0-23, default: 3)"
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Solo archivar eventos, sin refrescar importers"
    )
    parser.add_argument(
        "--city",
        nargs="+",
        help="Ciudades especificas (ej: --city Madrid Paris)"
    )
    args = parser.parse_args()

    if args.once:
        print("[Scheduler] Modo --once: ejecutando Guardian ahora...")
        run_guardian(refresh=not args.no_refresh, cities=args.city)
    else:
        run_scheduler(hour=args.hour, cities=args.city)
