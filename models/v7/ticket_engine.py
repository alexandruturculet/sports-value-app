def build_ticket(results, min_ev=0.0, min_conf=0):

    if not results:
        return {"ticket": [], "avg_confidence": 0}

    # FILTER
    picks = [
        r for r in results
        if r.get("edge", {}).get("ev", 0) >= min_ev
    ]

    # SORT
    picks = sorted(
        picks,
        key=lambda x: x.get("edge", {}).get("ev", 0),
        reverse=True
    )

    # FORCE FALLBACK (IMPORTANT FIX)
    if len(picks) == 0:
        picks = sorted(
            results,
            key=lambda x: x.get("edge", {}).get("ev", 0),
            reverse=True
        )[:5]

    else:
        picks = picks[:5]

    ticket = []

    for p in picks:

        ticket.append({
            "match": p["match"],
            "prediction": p["prediction"],
            "ev": p.get("edge", {}).get("ev", 0),
            "kelly": p.get("edge", {}).get("kelly", 0),
            "confidence": p.get("confidence", 0)
        })

    avg = sum(p["confidence"] for p in picks) / len(picks)

    return {
        "ticket": ticket,
        "avg_confidence": round(avg, 2)
    }