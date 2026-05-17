def build_ticket(results, min_ev=0.0, min_conf=0):
    if not results:
        return {"ticket": [], "avg_confidence": 0}

    picks = [r for r in results if r.get("edge", {}).get("ev", 0) >= min_ev]
    picks = sorted(picks, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)

    if not picks:
        picks = sorted(results, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)[:5]
    else:
        picks = picks[:5]

    ticket = [
        {
            "match": p["match"],
            "kickoff": p.get("kickoff", ""),
            "prediction": p["prediction"],
            "ev": p.get("edge", {}).get("ev", 0),
            "kelly": p.get("edge", {}).get("kelly", 0),
            "confidence": p.get("confidence", 0),
        }
        for p in picks
    ]

    avg = sum(p["confidence"] for p in picks) / len(picks)
    return {"ticket": ticket, "avg_confidence": round(avg, 2)}