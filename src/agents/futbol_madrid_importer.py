"""
Importador de fútbol de Madrid via ESPN API.
Ligas: La Liga (esp.1), Copa del Rey (esp.copa)
Estadios de Madrid: Bernabéu (Real Madrid), Metropolitano (Atlético)
"""
import sys, os, re, requests
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import init_db, get_or_create_city, insert_event

ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_LEAGUES = [
    ("esp.1",    "La Liga"),
    ("esp.copa", "Copa del Rey"),
]

MADRID_VENUES = ["bernabeu", "bernabéu", "metropolitano", "civitas", "wanda", "vallecas", "rayo"]


def fetch_matches(league_slug: str, league_name: str, today: date, cutoff: date) -> list:
    url     = f"{ESPN_BASE}/{league_slug}/scoreboard"
    matches = []
    try:
        resp = requests.get(url, params={"dates": f"{today.strftime('%Y%m%d')}-{cutoff.strftime('%Y%m%d')}"}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Error {league_slug}: {e}")
        return []

    for event in data.get("events", []):
        try:
            name       = event.get("name", "")
            date_str   = event.get("date", "")[:10]
            comp       = event.get("competitions", [{}])[0]
            venue_info = comp.get("venue", {})
            venue_name = venue_info.get("fullName", "")
            venue_city = venue_info.get("address", {}).get("city", "")
            status     = event.get("status", {}).get("type", {}).get("name", "")
            links      = event.get("links", [])
            link       = links[0].get("href", "https://www.espn.com/soccer/") if links else "https://www.espn.com/soccer/"

            hora = ""
            raw_date = event.get("date", "")
            if "T" in raw_date:
                dt       = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                dt_local = dt + timedelta(hours=2)   # CEST (verano España)
                hora     = dt_local.strftime("%H:%M")

            combined = (venue_name + " " + venue_city).lower()
            if not any(v in combined for v in MADRID_VENUES + ["madrid"]):
                continue

            competitors = comp.get("competitors", [])
            home = away = ""
            for c in competitors:
                t = c.get("team", {}).get("displayName", "")
                if c.get("homeAway") == "home":
                    home = t
                elif c.get("homeAway") == "away":
                    away = t

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


def import_futbol_madrid():
    today  = date.today()
    cutoff = today + timedelta(days=90)

    print(f"\nImportando fútbol de Madrid (hasta {cutoff})...")
    init_db()
    city_id = get_or_create_city("Madrid", "España")

    total_imported = 0

    for league_slug, league_name in ESPN_LEAGUES:
        print(f"\nLiga: {league_name}")
        matches = fetch_matches(league_slug, league_name, today, cutoff)
        print(f"  {len(matches)} partidos en Madrid encontrados")

        for m in matches:
            venue_lower = m["venue"].lower()
            if "bernabeu" in venue_lower or "bernabéu" in venue_lower:
                ticket  = "https://www.realmadrid.com/entradas"
                address = "Av. de Concha Espina 1, Chamartín, Madrid"
            elif "metropolitano" in venue_lower or "civitas" in venue_lower or "wanda" in venue_lower:
                ticket  = "https://www.atleticodemadrid.com/entradas"
                address = "Av. Luis Aragonés 4, San Blas-Canillejas, Madrid"
            elif "vallecas" in venue_lower or "rayo" in venue_lower:
                ticket  = "https://www.rayovallecano.es"
                address = "Calle Payaso Fofó s/n, Vallecas, Madrid"
            else:
                ticket  = m["link"]
                address = m["venue"] + ", Madrid"

            safe_name = re.sub(r"[^a-z0-9]", "", m["name"].lower())[:30]
            event_id  = f"espn_mad_{league_slug}_{m['date']}_{safe_name}"

            event = {
                "event_id":         event_id,
                "name":             m["name"],
                "category":         f"Fútbol / {m['league']}",
                "venue":            m["venue"] or address,
                "start_date":       m["date"],
                "end_date":         m["date"],
                "time":             m["time"],
                "price":            "Entradas desde €20 - €300 EUR según partido y categoría (ver club oficial o entradas.com)",
                "ticket_source":    ticket,
                "official_source":  "https://www.espn.com/soccer/",
                "status":           "scheduled" if m["status"] in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS") else "completed",
                "confidence_level": "high",
                "is_free": 0, "is_indoor": 0, "target_audience": "todos",
            }
            insert_event(city_id, event)
            total_imported += 1
            print(f"    [{m['date']} {m['time']}] {m['name'][:55]} @ {m['venue'][:25]}")

    print(f"\nImportacion fútbol Madrid completada: {total_imported} partidos")


if __name__ == "__main__":
    import_futbol_madrid()
