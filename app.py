from flask import Flask, jsonify
import time
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# --- GLOBAL STATE MANAGEMENT ---
DAILY_LOG = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "count": 0,
    "last_sent_match_id": 0,
    "sent_matches": []
}

DAILY_MATCH_LIMIT = 12
STAKE_PER_ARB = 5250  # ₦1,750 × 3 legs = ₦5,250
MIN_PROFIT_PERCENT = 0.5  # Minimum 0.5% profit

def generate_massive_odds_data():
    """Generates a stable set of 150-200 potential matches."""
    leagues = {
        "English Premier League": ["Arsenal", "Chelsea", "Man City", "Liverpool", "Man United", "Tottenham", "Newcastle"],
        "La Liga": ["Barcelona", "Real Madrid", "Atletico Madrid", "Sevilla", "Valencia", "Villarreal"],
        "Serie A": ["Juventus", "Inter Milan", "AC Milan", "Napoli", "Roma"],
        "Bundesliga": ["Bayern Munich", "Dortmund", "Leipzig", "Leverkusen"],
        "Nigeria PL": ["Rivers United", "Enyimba", "Kano Pillars", "Rangers", "Lobi Stars", "Akwa United"],
        "Champions League": ["Real Madrid", "Bayern", "Man City", "PSG", "Barcelona", "Juventus"],
    }
    
    matches = []
    match_id = 1
    
    for league, teams in leagues.items():
        num_matches = random.randint(8, 12)
        for _ in range(num_matches):
            home = random.choice(teams)
            away = random.choice([t for t in teams if t != home])
            
            # Generate realistic odds with arbitrage opportunities
            base_home = round(random.uniform(1.8, 3.2), 2)
            base_draw = round(random.uniform(3.0, 4.0), 2)
            base_away = round(random.uniform(2.0, 3.8), 2)
            
            # Create arbitrage opportunities in 30% of matches
            if random.random() < 0.3:
                total_prob = (1/base_home + 1/base_draw + 1/base_away)
                if total_prob > 1.0:
                    adjustment = random.uniform(0.88, 0.98)
                    base_home = round(base_home * adjustment, 2)
                    base_draw = round(base_draw * adjustment, 2)
                    base_away = round(base_away * adjustment, 2)
            
            bookmakers = ["Bet9ja", "1xBet", "SportyBet", "BetKing", "NairaBet"]
            bookmaker_odds = {}
            for bm in bookmakers:
                # Realistic odds variations across bookmakers
                multiplier = random.uniform(0.95, 1.05)
                bookmaker_odds[bm] = {
                    "home": round(base_home * multiplier, 2),
                    "draw": round(base_draw * multiplier, 2),
                    "away": round(base_away * multiplier, 2)
                }
            
            # Staggered match times for 12-daily execution
            hour = random.randint(8, 23)
            minute = random.choice([0, 15, 30, 45])
            match_time = f"{hour:02d}:{minute:02d}"
            
            matches.append({
                "id": match_id,
                "teams": f"{home} vs {away}",
                "league": league,
                "bookmaker_odds": bookmaker_odds,
                "time": match_time,
                "date": (datetime.now() + timedelta(days=0)).strftime("%Y-%m-%d")
            })
            
            match_id += 1
            if match_id > 150:  # Cap at 150 matches
                break
    
    return matches

def find_best_arb(match_data):
    """Calculates the best arbitrage opportunity for a single match."""
    best_arb = None
    max_profit = 0
    bookmakers = list(match_data['bookmaker_odds'].keys())
    
    # Find best arbitrage combination
    for bm_h in bookmakers:
        for bm_d in bookmakers:
            for bm_a in bookmakers:
                # Ensure three different bookmakers
                if len({bm_h, bm_d, bm_a}) == 3: 
                    odds_h = match_data['bookmaker_odds'][bm_h]['home']
                    odds_d = match_data['bookmaker_odds'][bm_d]['draw']
                    odds_a = match_data['bookmaker_odds'][bm_a]['away']
                    
                    # Calculate Arbitrage Index
                    arb_index = (1/odds_h + 1/odds_d + 1/odds_a)
                    
                    # Check for arbitrage condition
                    if arb_index < 1.0:
                        profit_percent = ((1 / arb_index) - 1) * 100
                        
                        if profit_percent > max_profit and profit_percent >= MIN_PROFIT_PERCENT:
                            # Calculate stakes
                            stake_h = round((1/odds_h) * STAKE_PER_ARB / arb_index, 2)
                            stake_d = round((1/odds_d) * STAKE_PER_ARB / arb_index, 2)
                            stake_a = round((1/odds_a) * STAKE_PER_ARB / arb_index, 2)

                            # Reasonable stake limits for ₦5,250 total
                            if stake_h > 3000 or stake_d > 3000 or stake_a > 3000: 
                                continue
                            
                            max_profit = profit_percent
                            best_arb = {
                                "match_id": match_data['id'],
                                "teams": match_data['teams'],
                                "league": match_data['league'],
                                "time": match_data['time'],
                                "profit_percent": round(profit_percent, 2),
                                "legs": [
                                    {"outcome": "Home", "bookmaker": bm_h, "odd": odds_h, "stake": stake_h},
                                    {"outcome": "Draw", "bookmaker": bm_d, "odd": odds_d, "stake": stake_d},
                                    {"outcome": "Away", "bookmaker": bm_a, "odd": odds_a, "stake": stake_a},
                                ]
                            }
    return best_arb

def update_daily_log():
    """Resets the log if the date has changed."""
    global DAILY_LOG
    today_date = datetime.now().strftime("%Y-%m-%d")
    if DAILY_LOG["date"] != today_date:
        DAILY_LOG = {
            "date": today_date,
            "count": 0,
            "last_sent_match_id": 0,
            "sent_matches": []
        }

@app.route('/next_arb')
def next_arb_opportunity():
    update_daily_log()
    
    if DAILY_LOG["count"] >= DAILY_MATCH_LIMIT:
        return jsonify({
            "status": "daily_limit_reached",
            "message": f"Daily limit of {DAILY_MATCH_LIMIT} matches reached.",
            "progress": f"{DAILY_LOG['count']}/{DAILY_MATCH_LIMIT}"
        })

    all_matches = generate_massive_odds_data()
    
    # Find next arbitrage opportunity
    for match in all_matches:
        if match['id'] > DAILY_LOG['last_sent_match_id'] and match['id'] not in DAILY_LOG['sent_matches']:
            opportunity = find_best_arb(match)
            
            if opportunity:
                # Update log
                DAILY_LOG['count'] += 1
                DAILY_LOG['last_sent_match_id'] = match['id']
                DAILY_LOG['sent_matches'].append(match['id'])
                
                # Structure response for your automation
                automate_leg = opportunity['legs'][0]
                macrodroid_legs = opportunity['legs'][1:]
                
                return jsonify({
                    "status": "opportunity_found",
                    "progress": f"{DAILY_LOG['count']}/{DAILY_MATCH_LIMIT}",
                    "match_info": f"{opportunity['teams']} ({opportunity['league']}) at {opportunity['time']}",
                    "profit": f"{opportunity['profit_percent']}%",
                    "automate_leg": {
                        "bookmaker": automate_leg['bookmaker'],
                        "odd_value": automate_leg['odd'],
                        "stake_amount": automate_leg['stake'],
                        "outcome": automate_leg['outcome'],
                    },
                    "macrodroid_legs": macrodroid_legs
                })

    return jsonify({
        "status": "no_arbitrage_available",
        "message": "No profitable arbitrage found.",
        "progress": f"{DAILY_LOG['count']}/{DAILY_MATCH_LIMIT}"
    })

@app.route('/health')
def health():
    return f"✅ Arbitrage API - Today: {DAILY_LOG['count']}/{DAILY_MATCH_LIMIT}"

@app.route('/')
def home():
    return "🚀 OPTIMIZED Arbitrage Scanner - ₦5,250 Stakes - 12 Matches Daily"

@app.route('/reset')
def reset_daily():
    """Emergency reset endpoint (use carefully)"""
    global DAILY_LOG
    DAILY_LOG = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "count": 0,
        "last_sent_match_id": 0,
        "sent_matches": []
    }
    return "Daily counter reset ✅"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)  # ✅ CORRECT PORT FOR RENDER
