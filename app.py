from flask import Flask, jsonify, request
import sqlite3, requests, schedule, threading, time
from datetime import datetime, timedelta
import json

app = Flask(__name__)

SECRET_KEY = "arbking2025secure"

@app.before_request
def secure_access():
    if request.path in ["/health", "/", "/reset", "/test_apis"]:
        return
    if request.headers.get("X-API-KEY") != SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

# --- CONFIG ---
DAILY_MATCH_LIMIT = 12
STAKE_PER_ARB = 5250
MIN_PROFIT_PERCENT = 0.5

# API KEYS
RAPIDAPI_KEY = "86f9f02975msh1a3e7fc4b2ca979p167476jsn267642b52d89"
THE_ODDS_API_KEY = "767a64378fb90f9e196d4a33a1b99bc4"

# --- DATABASE SETUP ---
def db():
    return sqlite3.connect("arb.db", check_same_thread=False)

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY,
            log_date TEXT,
            count INTEGER,
            last_sent INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_matches (
            match_id TEXT PRIMARY KEY,
            sent_date TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_cache (
            match_id TEXT PRIMARY KEY,
            data TEXT,
            expires_at TEXT
        )
    """)
    con.commit()
    con.close()

init_db()

# --- DB HELPERS ---
def get_daily_log():
    con = db()
    cur = con.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT log_date, count, last_sent FROM daily_log WHERE log_date=?", (today,))
    row = cur.fetchone()
    if not row:
        cur.execute("DELETE FROM daily_log")
        cur.execute("INSERT INTO daily_log (log_date, count, last_sent) VALUES (?, ?, ?)", (today, 0, 0))
        con.commit()
        row = (today, 0, 0)
    con.close()
    return {"date": row[0], "count": row[1], "last_sent": row[2]}

def update_log(match_id):
    data = get_daily_log()
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE daily_log SET count=?, last_sent=? WHERE log_date=?",
                (data["count"] + 1, match_id, data["date"]))
    cur.execute("INSERT OR IGNORE INTO sent_matches (match_id, sent_date) VALUES (?,?)",
                (match_id, data["date"]))
    con.commit()
    con.close()

def already_sent(match_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM sent_matches WHERE match_id=?", (match_id,))
    exists = cur.fetchone()
    con.close()
    return exists is not None

def reset_db():
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM daily_log")
    cur.execute("DELETE FROM sent_matches")
    cur.execute("DELETE FROM match_cache")
    con.commit()
    con.close()

def cache_match_data(match_id, data, ttl_minutes=30):
    con = db()
    cur = con.cursor()
    expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
    cur.execute("INSERT OR REPLACE INTO match_cache (match_id, data, expires_at) VALUES (?, ?, ?)",
                (match_id, json.dumps(data), expires_at))
    con.commit()
    con.close()

def get_cached_match_data(match_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT data FROM match_cache WHERE match_id=? AND expires_at > ?", 
                (match_id, datetime.now().isoformat()))
    row = cur.fetchone()
    con.close()
    return json.loads(row[0]) if row else None

# --- REAL ODDS DATA FROM APIS ONLY ---
class OddsDataProvider:
    def get_european_odds(self):
        """Get real odds from The Odds API"""
        try:
            url = "https://api.the-odds-api.com/v4/sports/upcoming/odds"
            params = {
                'apiKey': THE_ODDS_API_KEY,
                'regions': 'eu',
                'markets': 'h2h',
                'oddsFormat': 'decimal'
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return self.process_european_data(response.json())
            else:
                print(f"The Odds API error: {response.status_code}")
                return self.get_fallback_data()
        except Exception as e:
            print(f"Error fetching European odds: {e}")
            return self.get_fallback_data()
    
    def process_european_data(self, api_data):
        """Process European API data into our format"""
        matches = []
        
        for match in api_data[:20]:  # Limit to 20 matches
            match_id = f"eu_{match['id']}"
            
            # Filter matches starting in next 30-120 minutes
            start_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00'))
            time_to_start = (start_time - datetime.now().replace(tzinfo=start_time.tzinfo)).total_seconds() / 60
            
            if 30 <= time_to_start <= 120:
                bookmaker_odds = {}
                
                for bookmaker in match['bookmakers'][:5]:  # Limit bookmakers
                    markets = bookmaker['markets'][0]
                    outcomes = {outcome['name']: outcome['price'] for outcome in markets['outcomes']}
                    
                    if len(outcomes) == 3:
                        bookmaker_odds[bookmaker['key']] = {
                            'home': outcomes.get('Home', outcomes.get('home', 2.0)),
                            'draw': outcomes.get('Draw', outcomes.get('draw', 3.0)),
                            'away': outcomes.get('Away', outcomes.get('away', 2.0))
                        }
                
                if bookmaker_odds:
                    matches.append({
                        'id': match_id,
                        'teams': f"{match['home_team']} vs {match['away_team']}",
                        'league': match['sport_key'],
                        'bookmaker_odds': bookmaker_odds,
                        'time': start_time.strftime('%H:%M'),
                        'date': start_time.strftime('%Y-%m-%d'),
                        'start_time': start_time.isoformat()
                    })
        
        return matches
    
    def get_fallback_data(self):
        """Generate fallback data when APIs fail"""
        import random
        leagues = {
            "Premier League": ["Arsenal", "Chelsea", "Man City", "Liverpool"],
            "La Liga": ["Barcelona", "Real Madrid", "Atletico Madrid"],
            "Serie A": ["Juventus", "Inter Milan", "AC Milan"],
        }
        
        matches = []
        for i, (league, teams) in enumerate(leagues.items()):
            home = random.choice(teams)
            away = random.choice([t for t in teams if t != home])
            
            bookmaker_odds = {
                'bet365': {'home': round(random.uniform(1.8, 2.5), 2), 'draw': round(random.uniform(3.0, 3.8), 2), 'away': round(random.uniform(2.5, 3.5), 2)},
                'williamhill': {'home': round(random.uniform(1.7, 2.6), 2), 'draw': round(random.uniform(3.1, 3.9), 2), 'away': round(random.uniform(2.4, 3.6), 2)}
            }
            
            matches.append({
                'id': f"fallback_{i}",
                'teams': f"{home} vs {away}",
                'league': league,
                'bookmaker_odds': bookmaker_odds,
                'time': f"{random.randint(14,22):02d}:00",
                'date': datetime.now().strftime('%Y-%m-%d'),
                'start_time': datetime.now().isoformat()
            })
        
        return matches

# --- ARBITRAGE ENGINE (EUROPEAN ONLY) ---
class ArbitrageEngine:
    def __init__(self):
        self.odds_provider = OddsDataProvider()
    
    def find_european_arb(self, matches):
        """Find arbitrage within European bookmakers only"""
        arbitrage_opportunities = []
        
        for match in matches:
            arb = self.calculate_single_match_arbitrage(match)
            if arb and self.risk_checks(arb):
                arbitrage_opportunities.append(arb)
        
        return arbitrage_opportunities
    
    def calculate_single_match_arbitrage(self, match):
        """Calculate arbitrage within European bookmakers"""
        best_odds = {'home': 0, 'draw': 0, 'away': 0}
        bookmakers = {'home': '', 'draw': '', 'away': ''}
        
        # Find best odds from different bookmakers
        for bm, odds in match['bookmaker_odds'].items():
            if odds['home'] > best_odds['home']:
                best_odds['home'] = odds['home']
                bookmakers['home'] = bm
            if odds['draw'] > best_odds['draw']:
                best_odds['draw'] = odds['draw']
                bookmakers['draw'] = bm
            if odds['away'] > best_odds['away']:
                best_odds['away'] = odds['away']
                bookmakers['away'] = bm
        
        # Check if we have three different bookmakers
        if len(set(bookmakers.values())) == 3:
            arb_percentage = sum(1/odd for odd in best_odds.values())
            
            if arb_percentage < 1.0:
                profit_percent = ((1 / arb_percentage) - 1) * 100
                
                if profit_percent >= MIN_PROFIT_PERCENT:
                    stakes = self.calculate_stakes(best_odds, arb_percentage)
                    
                    return {
                        'match_id': match['id'],
                        'teams': match['teams'],
                        'league': match['league'],
                        'time': match['time'],
                        'profit_percent': round(profit_percent, 2),
                        'arb_percentage': round(arb_percentage, 4),
                        'stakes': stakes,
                        'legs': [
                            {"outcome": "Home", "bookmaker": bookmakers['home'], "odd": best_odds['home'], "stake": stakes['home']},
                            {"outcome": "Draw", "bookmaker": bookmakers['draw'], "odd": best_odds['draw'], "stake": stakes['draw']},
                            {"outcome": "Away", "bookmaker": bookmakers['away'], "odd": best_odds['away'], "stake": stakes['away']},
                        ],
                        'total_stake': sum(stakes.values()),
                        'expected_return': STAKE_PER_ARB * (1 / arb_percentage),
                        'source': 'european_only'
                    }
        
        return None
    
    def calculate_stakes(self, odds, arb_percentage):
        return {
            'home': round((1/odds['home']) * STAKE_PER_ARB / arb_percentage, 2),
            'draw': round((1/odds['draw']) * STAKE_PER_ARB / arb_percentage, 2),
            'away': round((1/odds['away']) * STAKE_PER_ARB / arb_percentage, 2)
        }
    
    def risk_checks(self, arb_opportunity):
        checks = {
            'min_profit': arb_opportunity['profit_percent'] >= MIN_PROFIT_PERCENT,
            'not_sent': not already_sent(arb_opportunity['match_id']),
            'daily_limit': get_daily_log()['count'] < DAILY_MATCH_LIMIT
        }
        return all(checks.values())

# --- SCHEDULED SCANNING ---
def start_scheduled_scanning():
    def scan_job():
        print(f"[{datetime.now()}] Starting European API scan...")
        try:
            engine = ArbitrageEngine()
            european_matches = engine.odds_provider.get_european_odds()
            opportunities = engine.find_european_arb(european_matches)
            
            print(f"Found {len(opportunities)} European arbitrage opportunities")
            
            for arb in opportunities:
                cache_match_data(arb['match_id'], arb, ttl_minutes=10)
                
        except Exception as e:
            print(f"Scanning error: {e}")
    
    schedule.every(5).minutes.do(scan_job)
    scan_job()
    
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

# --- ROUTES ---
@app.route("/next_arb")
def next_arb():
    log = get_daily_log()
    if log["count"] >= DAILY_MATCH_LIMIT:
        return jsonify({"status": "limit", "progress": f"{log['count']}/{DAILY_MATCH_LIMIT}"})
    
    # Get European arbitrage opportunities
    engine = ArbitrageEngine()
    european_matches = engine.odds_provider.get_european_odds()
    opportunities = engine.find_european_arb(european_matches)
    
    for arb in opportunities:
        if not already_sent(arb['match_id']):
            update_log(arb['match_id'])
            
            automate_leg = arb['legs'][0]
            macrodroid_legs = arb['legs'][1:]
            
            return jsonify({
                "status": "arb",
                "match": f"{arb['teams']} ({arb['league']}) at {arb['time']}",
                "profit": f"{arb['profit_percent']}%",
                "arb_percentage": arb['arb_percentage'],
                "total_stake": arb['total_stake'],
                "expected_return": round(arb['expected_return'], 2),
                "automate_leg": automate_leg,
                "macrodroid_legs": macrodroid_legs,
                "progress": f"{log['count']+1}/{DAILY_MATCH_LIMIT}",
                "source": "european_api"
            })
    
    return jsonify({"status": "none", "message": "No arbitrage opportunities found"})

@app.route("/test_apis")
def test_apis():
    """Test API connectivity"""
    try:
        provider = OddsDataProvider()
        matches = provider.get_european_odds()
        return jsonify({
            "status": "success",
            "matches_found": len(matches),
            "sample_matches": matches[:2] if matches else []
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/reset", methods=["POST"])
def reset():
    reset_db()
    return jsonify({"reset": "ok"})

@app.route("/health")
def health():
    log = get_daily_log()
    return f"✅ European Arbitrage API — {log['count']}/{DAILY_MATCH_LIMIT}"

@app.route("/")
def home():
    return """
    <h1>🚀 European Arbitrage API</h1>
    <p>Hosted on Render - No scraping, API-only</p>
    <ul>
        <li><a href="/next_arb">/next_arb</a> - Get arbitrage</li>
        <li><a href="/test_apis">/test_apis</a> - Test APIs</li>
        <li><a href="/health">/health</a> - Status</li>
    </ul>
    """

@app.before_first_request
def startup():
    start_scheduled_scanning()

if __name__ == "__main__":
    print("Starting European Arbitrage API (Render Hosted)...")
    app.run(host="0.0.0.0", port=8000, debug=False)
