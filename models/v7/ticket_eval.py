"""Ticket pick evaluation — pure logic, no Streamlit/API dependencies."""


def pick_won(prediction: str, h: int, a: int) -> bool:
    """Evaluate whether a pick was correct given the final score."""
    p = prediction.strip()
    if p == "1":
        return h > a
    if p == "2":
        return a > h
    if p == "X":
        return h == a
    if p == "1X":
        return h >= a
    if p == "X2":
        return a >= h
    if p == "BTTS":
        return h >= 1 and a >= 1
    if p in ("Over 2.5", "Over2.5"):
        return h + a >= 3
    if p in ("Under 2.5", "Under2.5"):
        return h + a <= 2
    return False
