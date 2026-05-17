# Maps API team name → (display name, Wikipedia article title for image lookup)
TOP_PLAYERS: dict[str, tuple[str, str]] = {

    # ── England ────────────────────────────────────────────────────────────────
    "Arsenal FC":                   ("Bukayo Saka",          "Bukayo Saka"),
    "Manchester City FC":           ("Erling Haaland",       "Erling Haaland"),
    "Liverpool FC":                 ("Mohamed Salah",        "Mohamed Salah"),
    "Chelsea FC":                   ("Cole Palmer",          "Cole Palmer (footballer)"),
    "Tottenham Hotspur FC":         ("Son Heung-min",        "Son Heung-min"),
    "Manchester United FC":         ("Bruno Fernandes",      "Bruno Fernandes (footballer, born 1994)"),
    "Newcastle United FC":          ("Alexander Isak",       "Alexander Isak"),
    "Aston Villa FC":               ("Ollie Watkins",        "Ollie Watkins"),
    "West Ham United FC":           ("Jarrod Bowen",         "Jarrod Bowen"),
    "Brighton & Hove Albion FC":    ("João Pedro",           "João Pedro (footballer, born 2001)"),
    "Everton FC":                   ("Abdoulaye Doucouré",   "Abdoulaye Doucouré"),
    "Fulham FC":                    ("Andreas Pereira",      "Andreas Pereira"),
    "Wolverhampton Wanderers FC":   ("Matheus Cunha",        "Matheus Cunha"),
    "Crystal Palace FC":            ("Eberechi Eze",         "Eberechi Eze"),
    "Brentford FC":                 ("Bryan Mbeumo",         "Bryan Mbeumo"),
    "Nottingham Forest FC":         ("Anthony Elanga",       "Anthony Elanga"),
    "AFC Bournemouth":              ("Antoine Semenyo",      "Antoine Semenyo"),
    "Leicester City FC":            ("Jamie Vardy",          "Jamie Vardy"),
    "Southampton FC":               ("Tyler Dibling",        "Tyler Dibling"),
    "Ipswich Town FC":              ("Liam Delap",           "Liam Delap"),

    # ── Spain ──────────────────────────────────────────────────────────────────
    "Real Madrid CF":               ("Kylian Mbappé",        "Kylian Mbappé"),
    "FC Barcelona":                 ("Lamine Yamal",         "Lamine Yamal"),
    "Atlético Madrid":              ("Antoine Griezmann",    "Antoine Griezmann"),
    "Athletic Club":                ("Nico Williams",        "Nico Williams (footballer)"),
    "Real Sociedad de Fútbol":      ("Martín Zubimendi",     "Martín Zubimendi"),
    "Sevilla FC":                   ("Youssef En-Nesyri",    "Youssef En-Nesyri"),
    "Valencia CF":                  ("Hugo Duro",            "Hugo Duro"),
    "Villarreal CF":                ("Yeremy Pino",          "Yeremy Pino"),
    "Real Betis Balompié":          ("Isco",                 "Isco"),
    "Girona FC":                    ("Danjuma",              "Arnaut Danjuma"),
    "Getafe CF":                    ("Borja Mayoral",        "Borja Mayoral"),
    "Deportivo Alavés":             ("Kike García",          "Kike García"),

    # ── Italy ──────────────────────────────────────────────────────────────────
    "FC Internazionale Milano":     ("Lautaro Martínez",     "Lautaro Martínez"),
    "Juventus FC":                  ("Dušan Vlahović",       "Dušan Vlahović"),
    "AC Milan":                     ("Rafael Leão",          "Rafael Leão"),
    "SSC Napoli":                   ("Khvicha Kvaratskhelia","Khvicha Kvaratskhelia"),
    "AS Roma":                      ("Paulo Dybala",         "Paulo Dybala"),
    "SS Lazio":                     ("Valentín Castellanos", "Valentín Castellanos"),
    "Atalanta BC":                  ("Ademola Lookman",      "Ademola Lookman"),
    "ACF Fiorentina":               ("Moise Kean",           "Moise Kean"),
    "Torino FC":                    ("Duván Zapata",         "Duván Zapata"),
    "Bologna FC 1909":              ("Riccardo Orsolini",    "Riccardo Orsolini"),

    # ── Germany ────────────────────────────────────────────────────────────────
    "FC Bayern München":            ("Harry Kane",           "Harry Kane"),
    "Borussia Dortmund":            ("Serhou Guirassy",      "Serhou Guirassy"),
    "Bayer 04 Leverkusen":          ("Florian Wirtz",        "Florian Wirtz"),
    "RB Leipzig":                   ("Benjamin Šeško",       "Benjamin Šeško"),
    "VfB Stuttgart":                ("Deniz Undav",          "Deniz Undav"),
    "Eintracht Frankfurt":          ("Hugo Ekitiké",         "Hugo Ekitiké"),
    "SC Freiburg":                  ("Vincenzo Grifo",       "Vincenzo Grifo"),

    # ── France ─────────────────────────────────────────────────────────────────
    "Paris Saint-Germain FC":       ("Ousmane Dembélé",      "Ousmane Dembélé"),
    "Olympique de Marseille":       ("Mason Greenwood",      "Mason Greenwood"),
    "Olympique Lyonnais":           ("Alexandre Lacazette",  "Alexandre Lacazette"),
    "AS Monaco FC":                 ("Takumi Minamino",      "Takumi Minamino"),
    "LOSC Lille":                   ("Jonathan David",       "Jonathan David (Canadian footballer)"),
    "OGC Nice":                     ("Evann Guessand",       "Evann Guessand"),

    # ── Portugal ───────────────────────────────────────────────────────────────
    "SL Benfica":                   ("Ángel Di María",       "Ángel Di María"),
    "FC Porto":                     ("Galeno",               "Galeno (footballer)"),
    "Sporting CP":                  ("Viktor Gyökeres",      "Viktor Gyökeres"),
    "SC Braga":                     ("Vítor Oliveira",       "Vítor Oliveira (footballer, born 1996)"),

    # ── Netherlands ────────────────────────────────────────────────────────────
    "AFC Ajax":                     ("Brian Brobbey",        "Brian Brobbey"),
    "PSV Eindhoven":                ("Luuk de Jong",         "Luuk de Jong"),
    "Feyenoord":                    ("Santiago Giménez",     "Santiago Giménez (footballer)"),
    "AZ Alkmaar":                   ("Wouter Goes",          "Wouter Goes"),
}


def get_top_player(team_name: str) -> tuple[str, str] | tuple[None, None]:
    """Return (player_display_name, wikipedia_title) for team, or (None, None)."""
    entry = TOP_PLAYERS.get(team_name)
    if entry:
        return entry

    # Fuzzy fallback: substring match on team name
    team_lower = team_name.lower()
    for key, value in TOP_PLAYERS.items():
        if team_lower in key.lower() or key.lower() in team_lower:
            return value

    return None, None
