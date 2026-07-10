"""
Importador de deportes de New York City via ESPN API.
MLB: Yankees (mlb) y Mets (mlb)
NBA: Knicks y Nets (cuando inicia temporada)
"""
import sys, os, re, requests
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

NY_MLB_TEAMS  = ["new york yankees", "new york mets"]
NY_NBA_TEAMS  = ["new york knicks", "brooklyn nets"]
NY_NHL_TEAMS  = ["new york rangers", "new york islanders", "new york devils", "new jersey devils"]

VENUE_INFO = {
    "yankee stadium":  {"ticket": "https://www.mlb.com/yankees/tickets", "address": "1 E 161st St, The Bronx, NY 10451"},
    "citi field":      {"ticket": "https://www.mlb.com/mets/tickets",    "address": "41 Seaver Way, Flushing, Queens, NY 11368"},
    "madison square":  {"ticket": "https://www.msg.com",                  "address": "4 Pennsylvania Plaza, Midtown Manhattan, NY 10001"},
    "barclays":        {"ticket": "https://www.barclayscenter.com",       "address": "620 Atlantic Ave, Brooklyn, NY 11217"},
    "ubs arena":       {"ticket": "https://www.ubsarena.com",             "address": "2400 Hempstead Tpke, Elmont, NY 11003"},
}


def get_venue_info(venue_name: str) -> dict:
    vl = venue_name.lower()
    for key, info in VENUE_INFO.items():
        if key in vl:
            return info
    return {"ticket": "https://www.espn.com", "address": venue_name + ", New York, NY"}


def fetch_sport(sport: str, league: str, label: str, today: date, cutoff: date, ny_teams: list) -> list:
    url     = f"{ESPN_BASE}/{sport}/{league}/scoreboard"
    matches = []
    try:
        resp = requests.get(url, params={"dates": f"{today.strftime('%Y%m%d')}-{cutoff.strftime('%Y%m%d')}"}, timeout=20)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"  Error {league}: {e}")
        return []

    for event in events:
        try:
            name  = event.get("name", "")
            if not any(t in name.lower() for t in ny_teams):
                continue

            date_str   = event.get("date", "")[:10]
            comp       = event.get("competitions", [{}])[0]
            venue_info = comp.get("venue", {})
            venue_name = venue_info.get("fullName", "")
            status     = event.get("status", {}).get("type", {}).get("name", "")
            links      = event.get("links", [])
            link       = links[0].get("href", "https://www.espn.com") if links else "https://www.espn.com"

            hora = ""
            raw_date = event.get("date", "")
            if "T" in raw_date:
                dt       = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                dt_local = dt - timedelta(hours=4)   # EDT (verano NY)
                hora     = dt_local.strftime("%H:%M")

            competitors = comp.get("competitors", [])
            home = away = ""
            for c in competitors:
                t = c.get("team", {}).get("displayName", "")
                if c.get("homeAway") == "home":
                    home = t
                elif c.get("homeAway") == "away":
                    away = t

            venue_data = get_venue_info(venue_name)
            safe_name  = re.sub(r"[^a-z0-9]", "", name.lower())[:30]
            event_id   = f"espn_nyc_{league}_{date_str}_{safe_name}"

            if sport == "baseball":
                price = "Entradas desde $15 - $300+ USD según categoría y partido (ver MLB.com o SeatGeek)"
            elif sport == "basketball":
                price = "Entradas desde $45 - $500+ USD (ver msg.com o barclayscenter.com)"
            else:
                price = "Entradas desde $30 - $400+ USD según evento"

            matches.append({
                "event_id":         event_id,
                "name":             name,
                "category":         label,
                "venue":            venue_name or "New York, NY",
                "start_date":       date_str,
                "end_date":         date_str,
                "time":             hora,
                "price":            price,
                "ticket_source":    venue_data["ticket"],
                "official_source":  f"https://www.espn.com/{sport}/",
                "status":           "scheduled" if status in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS") else "completed",
                "confidence_level": "high",
                "is_free": 0, "is_indoor": 0 if sport == "baseball" else 1, "target_audience": "todos",
            })
        except Exception:
            continue

    return matches


def import_sports_nyc():
    today  = date.today()
    cutoff = today + timedelta(days=90)

    print(f"\nImportando deportes de New York City (hasta {cutoff})...")
    init_db()
    city_id = get_or_create_city("New York City", "United States")

    sports = [
        ("baseball", "mlb",  "Béisbol / MLB",     NY_MLB_TEAMS),
        ("basketball", "nba", "Basketball / NBA",  NY_NBA_TEAMS),
        ("hockey",   "nhl",  "Hockey / NHL",      NY_NHL_TEAMS),
    ]

    total = 0
    for sport, league, label, teams in sports:
        matches = fetch_sport(sport, league, label, today, cutoff, teams)
        print(f"  {label}: {len(matches)} partidos en NY")
        for m in matches:
            insert_event(city_id, m)
            print(f"    [{m['start_date']} {m['time']}] {m['name'][:55]}")
        total += len(matches)

    print(f"\nImportacion deportes NYC completada: {total} eventos")


if __name__ == "__main__":
    import_sports_nyc()
