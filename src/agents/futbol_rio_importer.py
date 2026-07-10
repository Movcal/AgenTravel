"""
Importador de fútbol de Rio de Janeiro via ESPN API.
Ligas: Brasileirão Série A (bra.1), Copa do Brasil (bra.copa)
Estadios de Rio: Maracanã, Nilton Santos (Engenhão), São Januário
"""
import sys, os, re, requests
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event, insert_place

ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_LEAGUES = [
    ("bra.1",    "Brasileirão Série A"),
    ("bra.copa", "Copa do Brasil"),
]

RIO_VENUES = ["maracanã", "maracana", "nilton santos", "engenhão", "engenhao",
              "são januário", "sao januario"]

STADIUM_PLACES = [
    {
        "name": "Estádio Jornalista Mário Filho (Maracanã)",
        "place_slug": "maracana_rio",
        "category": "Estádio de Fútbol / Ícono Olímpico",
        "description": "El estadio más icónico de Brasil y uno de los más famosos del mundo. Sede de Flamengo y Fluminense. Aforo: 78.838 personas. Tour disponible todos los días de 9h a 17h (R$70 adultos, R$35 meia). Fue sede de la Copa del Mundo 1950 y 2014, y de los Juegos Olímpicos 2016. La 'catedral del fútbol' brasileño.",
        "opening_hours": "Tours: 9h-17h todos los días (sin partido). Partidos: ver agenda oficial.",
        "closed_days": "Días de partido (solo acceso con entrada)",
        "price": "Tour: R$70 adultos | R$35 meia-entrada | Partidos desde R$30 (ver ingressos.com.br)",
        "currency": "BRL",
        "address": "Av. Pres. Castelo Branco, Portão 3 - Maracanã, Rio de Janeiro",
        "contact": "maracana.com.br | tours@maracana.com",
        "official_website": "https://maracana.com.br",
        "source": "https://maracana.com.br",
        "last_verified": date.today().isoformat(),
        "confidence_level": "high",
        "is_free": 0, "is_indoor": 0, "target_audience": "todos",
        "has_own_agenda": 1,
    },
    {
        "name": "Estádio Nilton Santos (Engenhão) — Botafogo",
        "place_slug": "engenhao_rio",
        "category": "Estádio de Fútbol",
        "description": "Estadio moderno del Botafogo de Futebol e Regatas. Aforo: 46.000 personas. Inaugurado en 2007, remodelado para los Juegos Olímpicos 2016. Equipado con cubierta total y buena visibilidad. Sede también de atletismo olímpico.",
        "opening_hours": "Solo días de partido (ver agenda do Botafogo)",
        "closed_days": "Sin partido: cerrado al público general",
        "price": "Entradas desde R$30 — ver botafogo.com.br",
        "currency": "BRL",
        "address": "Rua José dos Reis, 425 - Engenho de Dentro, Rio de Janeiro",
        "contact": "botafogo.com.br",
        "official_website": "https://www.botafogo.com.br",
        "source": "https://www.botafogo.com.br",
        "last_verified": date.today().isoformat(),
        "confidence_level": "high",
        "is_free": 0, "is_indoor": 0, "target_audience": "todos",
        "has_own_agenda": 1,
    },
    {
        "name": "Estádio São Januário — Vasco da Gama",
        "place_slug": "sao_januario_rio",
        "category": "Estádio de Fútbol / Patrimônio Histórico",
        "description": "Estadio del Club de Regatas Vasco da Gama, inaugurado en 1927. Patrimonio histórico de Rio. Aforo: 21.880 personas. Ambiente apasionado con la torcida vascaína. Cerca de la Feira de São Cristóvão.",
        "opening_hours": "Solo días de partido (ver agenda do Vasco)",
        "closed_days": "Sin partido: acceso restringido",
        "price": "Entradas desde R$25 — ver vasco.com.br",
        "currency": "BRL",
        "address": "Rua General Almério de Moura, 131 - São Cristóvão, Rio de Janeiro",
        "contact": "vasco.com.br",
        "official_website": "https://www.vasco.com.br",
        "source": "https://www.vasco.com.br",
        "last_verified": date.today().isoformat(),
        "confidence_level": "high",
        "is_free": 0, "is_indoor": 0, "target_audience": "todos",
        "has_own_agenda": 1,
    },
]


def fetch_matches(league_slug: str, league_name: str, today: date, cutoff: date) -> list:
    start_str = today.strftime("%Y%m%d")
    end_str   = cutoff.strftime("%Y%m%d")
    url       = f"{ESPN_BASE}/{league_slug}/scoreboard"
    matches   = []

    try:
        resp = requests.get(url, params={"dates": f"{start_str}-{end_str}"}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Error {league_slug}: {e}")
        return []

    for event in data.get("events", []):
        try:
            name       = event.get("name", "")
            date_str   = event.get("date", "")[:10]
            venue_info = event.get("competitions", [{}])[0].get("venue", {})
            venue_name = venue_info.get("fullName", "")
            venue_city = venue_info.get("address", {}).get("city", "")
            status     = event.get("status", {}).get("type", {}).get("name", "")
            links      = event.get("links", [])
            link       = links[0].get("href", "https://www.espn.com.br/futebol/") if links else "https://www.espn.com.br/futebol/"

            # Hora local (ESPN entrega UTC, Brasil = UTC-3)
            hora = ""
            raw_date = event.get("date", "")
            if "T" in raw_date:
                dt       = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                dt_local = dt - timedelta(hours=3)
                hora     = dt_local.strftime("%H:%M")

            # Filtrar por Rio de Janeiro
            combined = (venue_name + " " + venue_city).lower()
            if not any(v in combined for v in RIO_VENUES):
                continue

            # Competidores
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            home = away = ""
            for c in competitors:
                team_name = c.get("team", {}).get("displayName", "")
                if c.get("homeAway") == "home":
                    home = team_name
                elif c.get("homeAway") == "away":
                    away = team_name

            matches.append({
                "name":   name,
                "home":   home,
                "away":   away,
                "date":   date_str,
                "time":   hora,
                "venue":  venue_name,
                "status": status,
                "league": league_name,
                "link":   link,
            })
        except Exception:
            continue

    return matches


def import_futbol_rio():
    today  = date.today()
    cutoff = today + timedelta(days=90)

    print(f"\nImportando fútbol de Rio de Janeiro (hasta {cutoff})...")

    init_db()
    city_id = get_or_create_city("Rio de Janeiro", "Brasil")

    for place_data in STADIUM_PLACES:
        insert_place(city_id, place_data)
        print(f"  Place: {place_data['name']}")

    total_imported = 0

    for league_slug, league_name in ESPN_LEAGUES:
        print(f"\nLiga: {league_name}")
        matches = fetch_matches(league_slug, league_name, today, cutoff)
        print(f"  {len(matches)} partidos en Rio encontrados")

        for m in matches:
            venue_lower = m["venue"].lower()
            if "maracan" in venue_lower:
                ticket = "https://maracana.com.br/ingressos"
            elif "nilton" in venue_lower or "engenh" in venue_lower:
                ticket = "https://www.botafogo.com.br"
            elif "januar" in venue_lower:
                ticket = "https://www.vasco.com.br"
            else:
                ticket = m["link"]

            safe_name = re.sub(r"[^a-z0-9]", "", m["name"].lower())[:30]
            event_id  = f"espn_rio_{league_slug}_{m['date']}_{safe_name}"

            event = {
                "event_id":         event_id,
                "name":             m["name"],
                "category":         f"Fútbol / {m['league']}",
                "venue":            m["venue"] or "Rio de Janeiro",
                "start_date":       m["date"],
                "end_date":         m["date"],
                "time":             m["time"],
                "price":            "Entradas desde R$30 - R$300 BRL según categoría (ver ingressos.com.br o club oficial)",
                "ticket_source":    ticket,
                "official_source":  "https://www.espn.com.br/futebol/",
                "status":           "scheduled" if m["status"] in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS") else "completed",
                "confidence_level": "high",
                "is_free": 0, "is_indoor": 0, "target_audience": "todos",
            }
            insert_event(city_id, event)
            total_imported += 1
            print(f"    [{m['date']} {m['time']}] {m['name'][:55]} @ {m['venue'][:25]}")

    print(f"\nImportacion fútbol Rio completada: {total_imported} partidos")


if __name__ == "__main__":
    import_futbol_rio()
