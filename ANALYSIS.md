# Sports Value App - Analysis & Improvement Recommendations

## 1. 5-Minute Load Time Analysis

### Current Bottleneck
**Root Cause:** N+1 API problem
- `get_premier_league_standings()` → 1 API call
- `get_matches()` → 1 API call  
- **For each match:** `get_team_form()` + `get_team_goals()` → 3 API calls per team = **3-4 calls per match**
- With 10 matches = 30+ sequential API calls, each taking ~500ms-1s = **5+ minutes**

### Best Practices & Solutions

**Priority 1: Caching** (Immediate 80% improvement)
- Use `@st.cache_data(ttl=3600)` on heavy API calls to cache for 1 hour
- Impact: After first load, subsequent requests are instant
- Trade-off: Data is stale for up to 1 hour

```python
@st.cache_data(ttl=3600)
def get_premier_league_standings():
    # existing code

@st.cache_data(ttl=900)  # 15 min cache for team-specific data
def get_team_form(team_name):
    # existing code
```

**Priority 2: Parallel API Requests** (30-50% improvement)
- Use `concurrent.futures` or `asyncio` to fetch team data in parallel
- Instead of: request 1 → request 2 → request 3 (3 seconds)
- Do this: request 1, 2, 3 simultaneously (~1 second)

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_team_data_parallel(teams):
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(get_team_form, team): team for team in teams}
        results = {}
        for future in as_completed(futures):
            team = futures[future]
            results[team] = future.result()
    return results
```

**Priority 3: Batch Data Fetching**
- Instead of calling `get_team_goals()` per match, fetch all team stats in one batch query
- Some APIs support multi-team endpoints

**Priority 4: Loading State**
- Add progress indicators with `st.spinner()` so users know what's happening
- Displays progress instead of blank screen

```python
with st.spinner('Fetching standings...'):
    standings = get_premier_league_standings()
```

---

## 2. Date-Based Prediction Filtering

### Current State
App shows all upcoming matches (2-week default from odds API).

### Best Practices & Solutions

**Implementation:**
1. Add Streamlit date selector in sidebar
2. Filter matches by kick-off date client-side (fast, no API calls)
3. Store match date parsing with timezone awareness

```python
import streamlit as st
from datetime import datetime, timedelta
import pytz

# Sidebar date selector
date_filter = st.sidebar.selectbox(
    "Select prediction date",
    ["Today", "Tomorrow", "Next 7 days", "Next 14 days", "Custom"]
)

# Filter matches
def filter_matches_by_date(matches, date_filter):
    now = datetime.now(pytz.UTC)
    
    if date_filter == "Today":
        start = now.replace(hour=0, minute=0, second=0)
        end = now.replace(hour=23, minute=59, second=59)
    elif date_filter == "Tomorrow":
        tomorrow = now + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0)
        end = tomorrow.replace(hour=23, minute=59, second=59)
    # ... etc
    
    filtered = [m for m in matches if start <= datetime.fromisoformat(m['commence_time'].replace('Z', '+00:00')) <= end]
    return filtered
```

**Trade-offs:**
- ✅ No API change needed
- ✅ Instant filtering
- ❌ Can only filter from already-fetched matches
- **Solution:** Fetch 14-day matches once, filter locally

---

## 3. Romania Timezone Display

### Best Practices

**Use `pytz` or `zoneinfo` (Python 3.9+):**

```python
from datetime import datetime
import pytz

def display_time_in_romania(iso_time_string):
    utc_time = datetime.fromisoformat(iso_time_string.replace('Z', '+00:00'))
    romania_tz = pytz.timezone('Europe/Bucharest')
    local_time = utc_time.astimezone(romania_tz)
    return local_time.strftime("%a, %d %b %Y - %H:%M %Z")

# Usage in display
st.write(f"Kick-off: {display_time_in_romania(match['commence_time'])}")
```

**Trade-offs:**
- ✅ DST-aware (Europe/Bucharest handles UTC+2/+3 automatically)
- ✅ Minimal performance impact
- ✅ User-friendly display

---

## 4. Top 5 Leagues Expansion

### Current
- Premier League only (league=39)
- ~10-15 matches per day

### Top 5 Leagues
| League | API Code | Matches/day | Notes |
|--------|----------|------------|-------|
| Premier League | 39 | 10 | ~1-2 |
| La Liga | 140 | 8 | ~1-2 |
| Serie A | 135 | 8 | ~1-2 |
| Bundesliga | 78 | 8 | ~1-2 |
| Ligue 1 | 61 | 8 | ~1-2 |
| **TOTAL** | - | **40-50** | - |

### Performance Impact Analysis

**Current bottleneck per team:** 3 API calls × 3-4 leagues = 9-12 calls/team

**Worst case:** 50 matches × 2 teams × 12 API calls = 1,200 API calls = **10+ minutes**

### Best Practices & Solutions

**Solution Stack (in priority order):**

1. **Caching (CRITICAL)**
   ```python
   @st.cache_data(ttl=3600)
   def get_all_league_standings(leagues):
       # Batch fetch all leagues
       return {league: fetch_standings(league) for league in leagues}
   ```
   - Reduces from 1,200 calls to 0 (after initial load)

2. **Async/Parallel Requests**
   ```python
   # Fetch all matches from all 5 leagues simultaneously
   with ThreadPoolExecutor(max_workers=5) as executor:
       futures = [executor.submit(get_matches, league) for league in leagues]
       all_matches = [f.result() for f in as_completed(futures)]
   ```
   - Reduces 1,200 sequential calls to ~60 parallel batches

3. **Reduce Redundant Calls**
   - If a team plays in multiple leagues, cache their stats
   - Only fetch unique teams once

4. **Rate Limiting Awareness**
   - Most sports APIs have rate limits (e.g., 500 calls/month free tier)
   - Check your API quota before expanding
   - Consider upgrading API tier

### Verdict
**With caching + async:** Feasible but requires optimization
- First load: 2-3 minutes (acceptable)
- Subsequent loads: <1 second (excellent)
- **Recommendation:** Implement caching + async before expanding

---

## 5. Multiple Prediction Types (Advanced Feature)

### Current State
Only 1X2 (home/draw/away wins)

### Advanced Prediction Types

| Type | Name | Requirements | Complexity |
|------|------|--------------|-----------|
| BTTS | Both Teams to Score | Track avg goals/team, goal frequency | Medium |
| O0.5 1H | Over 0.5 goals first half | First half historical data | Medium |
| O1.5 | Over 1.5 total goals | Team attack/defense stats | Low |
| O2.5 | Over 2.5 total goals | Match intensity analysis | Low |
| BTTS+O2.5 | BTTS and Over 2.5 | Combined probabilities | Medium |
| First Scorer | Which player scores first | Player form data | High |
| Correct Score | Exact final score | Requires Poisson distribution | High |

### Statistical Foundation

**For BTTS prediction:**
```python
def predict_btts(home_goals_avg, away_goals_avg, home_concedes_avg, away_concedes_avg):
    # Probability home team scores: using Poisson distribution
    from scipy.stats import poisson
    
    home_scoring_prob = 1 - poisson.cdf(0, home_goals_avg)
    away_scoring_prob = 1 - poisson.cdf(0, away_goals_avg)
    
    btts_probability = home_scoring_prob * away_scoring_prob
    return btts_probability

def predict_over_under(home_goals_avg, away_goals_avg, threshold):
    from scipy.stats import poisson
    
    expected_goals = home_goals_avg + away_goals_avg
    over_prob = 1 - poisson.cdf(threshold - 1, expected_goals)
    return over_prob
```

### Implementation Plan

**Phase 1: Basic Extension** (1-2 hours)
```python
predictions = {
    "1X2": calculate_1x2_score(...),
    "O1.5": predict_over_under(...),
    "O2.5": predict_over_under(...)
}

# Display all types in tabs
tabs = st.tabs(["1X2 Picks", "Over 1.5", "Over 2.5"])
with tabs[0]:
    display_1x2_predictions()
# ... etc
```

**Phase 2: Statistical Models** (3-4 hours)
- Implement Poisson distribution for goal prediction
- Add team-specific attack/defense stats
- Calibrate model with historical data

**Phase 3: Market Integration** (2-3 hours)
- Fetch different market types from odds API (`markets=h2h,totals,btts`)
- Map predictions to available odds
- Calculate value bets

### Best Practices

1. **Use Poisson Model** for goal predictions
   - Standard for sports analytics
   - Proven accuracy

2. **Separate Prediction Engine**
   ```
   models/prediction.py
   ├── btts_predictor()
   ├── over_under_predictor()
   ├── goal_predictor()
   └── value_calculator()
   ```

3. **Cache Predictions**
   ```python
   @st.cache_data(ttl=1800)
   def generate_all_predictions(match):
       return {
           "1x2": ...,
           "btts": ...,
           "over_under": ...
       }
   ```

4. **Performance Trade-off**
   - Each additional prediction type adds ~200-500ms per match
   - With 50 matches: +10-25 seconds total
   - Offset with caching (after first load: instant)

---

## Summary Roadmap

| Priority | Task | Time | Impact |
|----------|------|------|--------|
| 🔴 1 | Add `@st.cache_data` to all API calls | 10 min | 95% speed improvement |
| 🔴 2 | Implement parallel requests | 30 min | 50% more speed |
| 🟡 3 | Add date filtering UI | 15 min | UX improvement |
| 🟡 4 | Display times in Romania timezone | 10 min | UX improvement |
| 🟢 5 | Expand to top 5 leagues (after caching) | 45 min | 5x more picks |
| 🟢 6 | Add BTTS + Over/Under predictions | 2-3 hrs | Advanced analytics |

---

## Code Priority: Do First

```python
# Add this immediately
@st.cache_data(ttl=3600)
def get_premier_league_standings():
    # existing code

@st.cache_data(ttl=900)
def get_team_form(team_name):
    # existing code

@st.cache_data(ttl=900)
def get_team_goals(team_name):
    # existing code
```

**Expected result:** 5 minutes → 30 seconds on first load, instant on refresh
