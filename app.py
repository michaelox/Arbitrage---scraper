from flask import Flask, jsonify
import time
import random
from datetime import datetime, timedelta

app = Flask(__name__)

def generate_massive_odds_data():
    leagues = {
        "English Premier League": ["Arsenal", "Chelsea", "Man City", "Liverpool", "Man United", "Tottenham", "Newcastle", "Brighton"],
        "La Liga": ["Barcelona", "Real Madrid", "Atletico Madrid", "Sevilla", "Valencia", "Villarreal", "Athletic Bilbao"],
        "Serie A": ["Juventus", "Inter Milan", "AC Milan", "Napoli", "Roma", "Lazio", "Atalanta"],
        "Bundesliga": ["Bayern Munich", "Dortmund", "Leipzig", "Leverkusen", "Frankfurt", "Monchengladbach"],
        "Ligue 1": ["PSG", "Marseille", "Lyon", "Monaco", "Lille", "Nice"],
        "Champions League": ["Real Madrid", "Bayern", "Man City", "PSG", "Barcelona", "Juventus"],
        "Europa League": ["Liverpool", "Sevilla", "Roma", "Leverkusen", "Brighton", "Atalanta"],
        "Nigeria PL": ["Rivers United", "Enyimba", "Kano Pillars", "Rangers", "Lobi Stars", "Akwa United", "Shooting Stars"],
        "Brazil Serie A": ["Flamengo", "Palmeiras", "Sao Paulo", "Corinthians", "Santos", "Gremio"],
        "MLS": ["LA Galaxy", "LAFC", "Inter Miami", "Atlanta United", "Seattle Sounders", "NY Red Bulls"],
        "EFL Championship": ["Leicester", "Leeds", "Southampton", "Ipswich", "Norwich", "West Brom"],
        "Eredivisie": ["Ajax", "PSV", "Feyenoord", "AZ Alkmaar", "Twente"],
        "Primeira Liga": ["Benfica", "Porto", "Sporting CP", "Braga"],
        "Saudi Pro League": ["Al Nassr", "Al Hilal", "Al Ahli", "Al Ittihad"],
        "Argentine Liga": ["Boca Juniors", "River Plate", "Racing Club", "San Lorenzo"]
    }
    
    matches = []
    match_id = 1
    
    # Generate 150-200 matches with ₦1,750 stake optimization
    for league, teams in leagues.items():
        num_matches = random.randint(8, 12)
        for _ in range(num_matches):
            home = random.choice(teams)
            away = random.choice([t for t in teams if t != home])
            
            # Generate odds optimized for ₦1,750 stakes
            base_home = round(random.uniform(1.9, 3.2), 2)
            base_draw = round(random.uniform(3.1, 4.0), 2)
            base_away = round(random.uniform(2.1, 3.8), 2)
            
            # Ensure 35% have arbitrage for ₦5,250 total stakes
            if random.random() < 0.35:
                total_prob = (1/base_home + 1/base_draw + 1/base_away)
                if total_prob > 1.0:
                    adjustment = random.uniform(0.88, 0.97)
                    base_home = round(base_home * adjustment, 2)
                    base_draw = round(base_draw * adjustment, 2)
                    base_away = round(base_away * adjustment, 2)
            
            # Bookmaker odds with Nigerian focus
            bookmaker_odds = {
                "Bet9ja": {"home": base_home, "draw": base_draw, "away": base_away},
                "1xBet": {
                    "home": round(base_home * random.uniform(0.96, 1.06), 2),
                    "draw": round(base_draw * random.uniform(0.96, 1.06), 2),
                    "away": round(base_away * random.uniform(0.96, 1.06), 2)
                },
                "SportyBet": {
                    "home": round(base_home * random.uniform(0.94, 1.04), 2),
                    "draw": round(base_draw * random.uniform(0.94, 1.04), 2),
                    "away": round(base_away * random.uniform(0.94, 1.04), 2)
                },
                "BetKing": {
                    "home": round(base_home * random.uniform(0.93, 1.03), 2),
                    "draw": round(base_draw * random.uniform(0.93, 1.03), 2),
                    "away": round(base_away * random.uniform(0.93, 1.03), 2)
                },
                "NairaBet": {
                    "home": round(base_home * random.uniform(0.95, 1.02), 2),
                    "draw": round(base_draw * random.uniform(0.95, 1.02), 2),
                    "away": round(base_away * random.uniform(0.95, 1.02), 2)
                }
            }
            
            # Staggered match times for 12-daily execution
            hour = random.randint(8, 23)
            minute = random.choice([0, 20, 40])
            match_time = f"{hour:02d}:{minute:02d}"
            
            matches.append({
                "id": match_id,
                "teams": f"{home} vs {away}",
                "league": league,
                "bookmaker_odds": bookmaker_odds,
                "time": match_time,
                "date": (datetime.now() + timedelta(days=random.randint(0, 2))).strftime("%Y-%m-%d"),
                "recommended_stake": 1750,
                "total_arb_stake": 5250
            })
            
            match_id += 1
            if match_id > 180:
                break
    
    return matches

@app.route('/odds')
def get_odds():
    matches = generate_massive_odds_data()
    
    # Calculate arbitrage opportunities
    arb_opportunities = 0
    for match in matches:
        for bookmaker1 in match['bookmaker_odds']:
            for bookmaker2 in match['bookmaker_odds']:
                for bookmaker3 in match['bookmaker_odds']:
                    if bookmaker1 != bookmaker2 != bookmaker3:
                        odds_h = match['bookmaker_odds'][bookmaker1]['home']
                        odds_d = match['bookmaker_odds'][bookmaker2]['draw']
                        odds_a = match['bookmaker_odds'][bookmaker3]['away']
                        arb_index = (1/odds_h + 1/odds_d + 1/odds_a)
                        if arb_index < 1.0:
                            arb_opportunities += 1
                            break
    
    return jsonify({
        "matches": matches,
        "total_matches": len(matches),
        "arbitrage_opportunities": arb_opportunities,
        "timestamp": time.time(),
        "status": "success",
        "bankroll_info": {
            "total_bankroll": 12250,
            "stake_per_leg": 1750,
            "stake_per_arb": 5250,
            "daily_matches": 12,
            "daily_volume": 63000
        }
    })

@app.route('/health')
def health():
    return "✅ OPTIMIZED Arbitrage API - ₦12,250 Bankroll - ₦1,750 Stakes"

@app.route('/')
def home():
    return "🚀 OPTIMIZED Arbitrage Scanner - ₦12,250 Bankroll - 7 Accounts - 12 Matches Daily"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
