from collections import defaultdict, deque

form_cache = defaultdict(lambda: deque(maxlen=5))


def add_match_result(team, goals_for, goals_against):

    if goals_for > goals_against:
        form_cache[team].append(3)
    elif goals_for == goals_against:
        form_cache[team].append(1)
    else:
        form_cache[team].append(0)


def get_form(team):

    form = list(form_cache[team])

    if not form:
        return {
            "form_points": 6,
            "trend": "unknown"
        }

    avg = sum(form) / len(form)

    trend = (
        "strong" if avg >= 2.2 else
        "medium" if avg >= 1.3 else
        "weak"
    )

    return {
        "form_points": avg,
        "trend": trend
    }