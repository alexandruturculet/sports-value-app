from models.v7.team_aliases import TEAM_ALIASES


def normalize(name: str):
    return (
        name.lower()
        .replace("fc", "")
        .replace("cf", "")
        .replace("ac", "")
        .replace("afc", "")
        .replace(".", "")
        .replace("-", " ")
        .strip()
    )


def resolve_team(name: str):

    n = normalize(name)

    # 1. direct canonical match
    for canonical, aliases in TEAM_ALIASES.items():

        canonical_norm = normalize(canonical)

        if n == canonical_norm:
            return canonical

        for a in aliases:
            if n == normalize(a):
                return canonical

    # 2. fallback safe
    return name