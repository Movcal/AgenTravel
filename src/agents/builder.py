"""
Agente Constructor (Builder)
Investiga una ciudad y llena la base de datos con lugares y eventos.
"""
import os
import json
import sys
import anthropic
from datetime import date
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_place, insert_event

BUILDER_SYSTEM_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "agent_builder.md"),
    encoding="utf-8"
).read()

TODAY = date.today().isoformat()
_t = date.today()
CUTOFF = date(_t.year if _t.month > 1 else _t.year - 1,
              _t.month - 1 if _t.month > 1 else 12, 1).isoformat()

TASKS = {
    "places": "Recolecta los 15 lugares permanentes mas importantes de {city} (museos, parques, monumentos, miradores, zoologicos, centros culturales). Devuelve UNICAMENTE un JSON valido con el array 'places'. El campo confidence_level debe ser exactamente 'high', 'medium' o 'low' en ingles y minusculas.",
    "events": "Recolecta hasta 15 eventos de {city} desde {cutoff} hasta 90 dias despues de {today}. NO incluir eventos anteriores a {cutoff}. Devuelve UNICAMENTE un JSON valido con el array 'events'. El campo confidence_level debe ser exactamente 'high', 'medium' o 'low' en ingles y minusculas.",
    "nightlife": "Recolecta los 10 mejores lugares de vida nocturna de {city} (teatros, musica en vivo, bares reconocidos, espectaculos). Devuelve UNICAMENTE un JSON valido con el array 'places'. El campo confidence_level debe ser exactamente 'high', 'medium' o 'low' en ingles y minusculas.",
    "free": "Recolecta los 10 mejores lugares y actividades GRATUITAS de {city}. Devuelve UNICAMENTE un JSON valido con el array 'places'. El campo confidence_level debe ser exactamente 'high', 'medium' o 'low' en ingles y minusculas.",
}

def run_task(client: anthropic.Anthropic, city: str, task_key: str) -> dict:
    prompt = TASKS[task_key].format(city=city, today=TODAY, cutoff=CUTOFF)
    print(f"\n[Builder] Tarea: {task_key} para {city}...")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=BUILDER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()

    # Extraer JSON de la respuesta
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [Error] JSON invalido en tarea {task_key}: {e}")
        print(f"  Respuesta recibida: {text[:200]}...")
        return {}

def build_city(city: str, country: str = None, tasks: list = None):
    """
    Construye la base de datos para una ciudad.
    tasks: lista de tareas a ejecutar. Si None, ejecuta todas.
    """
    if tasks is None:
        tasks = list(TASKS.keys())

    print(f"\n{'='*50}")
    print(f"  BUILDER - Construyendo: {city}")
    print(f"{'='*50}")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    init_db()

    city_id = get_or_create_city(city, country)
    print(f"Ciudad ID: {city_id}")

    total_places = 0
    total_events = 0

    for task_key in tasks:
        data = run_task(client, city, task_key)

        if "places" in data:
            print(f"\nGuardando {len(data['places'])} lugares...")
            for place in data["places"]:
                if place.get("name"):
                    insert_place(city_id, place)
                    total_places += 1

        if "events" in data:
            print(f"\nGuardando {len(data['events'])} eventos...")
            for event in data["events"]:
                if event.get("name"):
                    insert_event(city_id, event)
                    total_events += 1

    print(f"\n{'='*50}")
    print(f"  COMPLETADO: {city}")
    print(f"  Lugares guardados: {total_places}")
    print(f"  Eventos guardados: {total_events}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python builder.py <ciudad> [pais]")
        print("Ejemplo: python builder.py 'Buenos Aires' Argentina")
        print("         python builder.py Paris Francia")
        sys.exit(1)

    city = sys.argv[1]
    country = sys.argv[2] if len(sys.argv) > 2 else None
    build_city(city, country)
