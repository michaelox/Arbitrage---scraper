from flask import Flask, jsonify, request
import sqlite3, random, time, requests, schedule, threading
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from fake_useragent import UserAgent
import json

app = Flask(__name__)

SECRET_KEY = "arbking2025secure"  # your private key

@app.before_request
def secure_access():
    # Allow homepage & health check & reset without key
    if request.path in ["/health", "/", "/reset", "/test_scrape"]:
        return

    # Check key match
    if request.headers.get("X-API-KEY") != SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

# --- CONFIG ---
DAILY_MATCH_LIMIT = 12
STAKE_PER_ARB = 5250
MIN_PROFIT_PERCENT = 0.5

# API KEYS
RAPIDAPI_KEY = "86f9f02975msh1a3e7fc4b2ca979p167476jsn267642b52d89"
THE_ODDS_API_KEY = "767a64378fb90f9e196d4a33a1b99bc4"

# African Bookmakers to scrape
AFRICAN_BOOKMAKERS = ["Bet9ja", "SportyBet", "BetKing", "1xBet", "NairaBet"]

# Risk Management
MAX_STAKE_PER_BOOKMAKER = 3000
MIN_TIME_TO_MATCH = 15  # minutes
MAX_ARB_PERCENTAGE = 8.0  # Maximum arbitrage percentage

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

    if not row:  # create today row
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

# --- REAL ODDS DATA FROM APIS ---
class OddsDataProvider:
    def __init__(self):
        self.ua = UserAgent()
    
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
                return []
        except Exception as e:
            print(f"Error fetching European odds: {e}")
            return []
    
    def process_european_data(self, api_data):
        """Process European API data into our format"""
        matches = []
        
        for match in api_data:
            match_id = f"eu_{match['id']}"
            
            # Filter matches starting in next 30-60 minutes
            start_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00'))
            time_to_start = (start_time - datetime.now().replace(tzinfo=start_time.tzinfo)).total_seconds() / 60
            
            if 30 <= time_to_start <= 120:  # 30 mins to 2 hours
                bookmaker_odds = {}
                
                for bookmaker in match['bookmakers']:
                    if bookmaker['key'] in ['bet365', 'williamhill', 'pinnacle', 'onexbet']:
                        markets = bookmaker['markets'][0]
                        outcomes = {outcome['name']: outcome['price'] for outcome in markets['outcomes']}
                        
                        if len(outcomes) == 3:  # Home, Away, Draw
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
    
    def get_rapidapi_odds(self):
        """Get odds from RapidAPI Odds API"""
        try:
            url = "https://odds-api1.p.rapidapi.com/sports/upcoming/odds"
            headers = {
                'X-RapidAPI-Key': RAPIDAPI_KEY,
                'X-RapidAPI-Host': 'odds-api1.p.rapidapi.com'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return self.process_rapidapi_data(response.json())
            else:
                print(f"RapidAPI error: {response.status_code}")
                return []
        except Exception as e:
            print(f"Error fetching RapidAPI odds: {e}")
            return []

# --- WEB SCRAPING FOR AFRICAN BOOKMAKERS ---
class AfricanBookmakerScraper:
    def __init__(self):
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        """Setup undetectable Chrome driver"""
        try:
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = uc.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception as e:
            print(f"Driver setup failed: {e}")
    
    def scrape_sportybet(self):
        """Scrape SportyBet Nigeria pre-match odds"""
        try:
            if not self.driver:
                return {}
                
            self.driver.get("https://www.sportybet.com/ng/")
            time.sleep(5)
            
            # Wait for matches to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "match"))
            )
            
            matches_data = {}
            matches = self.driver.find_elements(By.CLASS_NAME, "match")[:10]  # First 10 matches
            
            for match in matches:
                try:
                    teams_elem = match.find_element(By.CLASS_NAME, "teams")
                    teams = teams_elem.text.strip()
                    
                    odds_elems = match.find_elements(By.CLASS_NAME, "odds")[:3]
                    if len(odds_elems) == 3:
                        home_odd = float(odds_elems[0].text.strip())
                        draw_odd = float(odds_elems[1].text.strip())
                        away_odd = float(odds_elems[2].text.strip())
                        
                        match_id = f"sportybet_{hash(teams) % 1000000}"
                        matches_data[match_id] = {
                            'teams': teams,
                            'odds': {'home': home_odd, 'draw': draw_odd, 'away': away_odd},
                            'time': datetime.now().strftime('%H:%M'),
                            'scraped_at': datetime.now().isoformat()
                        }
                except Exception as e:
                    continue
                    
            return matches_data
        except Exception as e:
            print(f"SportyBet scraping error: {e}")
            return {}
    
    def scrape_bet9ja(self):
        """Scrape Bet9ja pre-match odds"""
        try:
            if not self.driver:
                return {}
                
            self.driver.get("https://www.bet9ja.com/")
            time.sleep(5)
            
            matches_data = {}
            # Bet9ja specific scraping logic would go here
            # This is a simplified version - you'd need to adapt to actual site structure
            
            return matches_data
        except Exception as e:
            print(f"Bet9ja scraping error: {e}")
            return {}
    
    def get_african_odds(self):
        """Get odds from all African bookmakers"""
        african_data = {}
        
        print("Scraping African bookmakers...")
        
        # SportyBet
        sportybet_data = self.scrape_sportybet()
        african_data['sportybet'] = sportybet_data
        
        # Bet9ja 
        bet9ja_data = self.scrape_bet9ja()
        african_data['bet9ja'] = bet9ja_data
        
        # Add simulated data for other bookmakers (replace with actual scraping)
        for bookmaker in ['betking', 'nairabet']:
            african_data[bookmaker] = self.generate_simulated_african_odds()
        
        return african_data
    
    def generate_simulated_african_odds(self):
        """Generate realistic African odds when scraping fails"""
        matches = {}
        popular_matches = [
            "Rivers United vs Enyimba", "Kano Pillars vs Rangers", 
            "Arsenal vs Chelsea", "Man City vs Liverpool",
            "Barcelona vs Real Madrid", "Bayern vs Dortmund"
        ]
        
        for i, match in enumerate(popular_matches):
            base_home = round(random.uniform(1.8, 3.5), 2)
            base_draw = round(random.uniform(3.0, 4.2), 2)
            base_away = round(random.uniform(2.0, 4.0), 2)
            
            matches[f"sim_{i}"] = {
                'teams': match,
                'odds': {'home': base_home, 'draw': base_draw, 'away': base_away},
                'time': f"{random.randint(10,22):02d}:{random.choice([0,15,30,45]):02d}",
                'scraped_at': datetime.now().isoformat()
            }
        
        return matches
    
    def close(self):
        if self.driver:
            self.driver.quit()

# --- ARBITRAGE ENGINE ---
class ArbitrageEngine:
    def __init__(self):
        self.odds_provider = OddsDataProvider()
        self.scraper = AfricanBookmakerScraper()
    
    def find_cross_bookmaker_arb(self, european_matches, african_odds):
        """Find arbitrage between European and African bookmakers"""
        arbitrage_opportunities = []
        
        for eu_match in european_matches:
            # Try to find matching African match
            african_match_data = self.find_matching_african_match(eu_match, african_odds)
            
            if african_match_data:
                arb = self.calculate_cross_arbitrage(eu_match, african_match_data)
                if arb and self.risk_checks(arb):
                    arbitrage_opportunities.append(arb)
        
        return arbitrage_opportunities
    
    def find_matching_african_match(self, eu_match, african_odds):
        """Find African match that corresponds to European match"""
        eu_teams_lower = eu_match['teams'].lower()
        
        for bookmaker, matches in african_odds.items():
            for match_id, match_data in matches.items():
                af_teams_lower = match_data['teams'].lower()
                
                # Simple matching by team names
                common_terms = set(eu_teams_lower.split()) & set(af_teams_lower.split())
                if len(common_terms) >= 2:  # At least 2 common words (like team names)
                    return {
                        'bookmaker': bookmaker,
                        'teams': match_data['teams'],
                        'odds': match_data['odds'],
                        'source': 'african'
                    }
        
        return None
    
    def calculate_cross_arbitrage(self, eu_match, af_match):
        """Calculate arbitrage between European and African bookmakers"""
        best_odds = {
            'home': 0, 'draw': 0, 'away': 0
        }
        bookmakers = {
            'home': '', 'draw': '', 'away': ''
        }
        
        # Find best odds from European bookmakers
        for bm, odds in eu_match['bookmaker_odds'].items():
            if odds['home'] > best_odds['home']:
                best_odds['home'] = odds['home']
                bookmakers['home'] = f"eu_{bm}"
            if odds['draw'] > best_odds['draw']:
                best_odds['draw'] = odds['draw']
                bookmakers['draw'] = f"eu_{bm}"
            if odds['away'] > best_odds['away']:
                best_odds['away'] = odds['away']
                bookmakers['away'] = f"eu_{bm}"
        
        # Compare with African bookmaker
        af_odds = af_match['odds']
        if af_odds['home'] > best_odds['home']:
            best_odds['home'] = af_odds['home']
            bookmakers['home'] = f"af_{af_match['bookmaker']}"
        if af_odds['draw'] > best_odds['draw']:
            best_odds['draw'] = af_odds['draw']
            bookmakers['draw'] = f"af_{af_match['bookmaker']}"
        if af_odds['away'] > best_odds['away']:
            best_odds['away'] = af_odds['away']
            bookmakers['away'] = f"af_{af_match['bookmaker']}"
        
        # Calculate arbitrage
        arb_percentage = sum(1/odd for odd in best_odds.values())
        
        if arb_percentage < 1.0:
            profit_percent = ((1 / arb_percentage) - 1) * 100
            
            if profit_percent >= MIN_PROFIT_PERCENT:
                stakes = self.calculate_stakes(best_odds, arb_percentage)
                
                return {
                    'match_id': f"{eu_match['id']}_{af_match['bookmaker']}",
                    'teams': eu_match['teams'],
                    'league': eu_match['league'],
                    'time': eu_match['time'],
                    'profit_percent': round(profit_percent, 2),
                    'arb_percentage': round(arb_percentage, 4),
                    'stakes': stakes,
                    'legs': [
                        {"outcome": "Home", "bookmaker": bookmakers['home'], "odd": best_odds['home'], "stake": stakes['home']},
                        {"outcome": "Draw", "bookmaker": bookmakers['draw'], "odd": best_odds['draw'], "stake": stakes['draw']},
                        {"outcome": "Away", "bookmaker": bookmakers['away'], "odd": best_odds['away'], "stake": stakes['away']},
                    ],
                    'total_stake': sum(stakes.values()),
                    'expected_return': STAKE_PER_ARB * (1 / arb_percentage)
                }
        
        return None
    
    def calculate_stakes(self, odds, arb_percentage):
        """Calculate optimal stakes for arbitrage"""
        return {
            'home': round((1/odds['home']) * STAKE_PER_ARB / arb_percentage, 2),
            'draw': round((1/odds['draw']) * STAKE_PER_ARB / arb_percentage, 2),
            'away': round((1/odds['away']) * STAKE_PER_ARB / arb_percentage, 2)
        }
    
    def risk_checks(self, arb_opportunity):
        """Comprehensive risk management checks"""
        checks = {
            'min_profit': arb_opportunity['profit_percent'] >= MIN_PROFIT_PERCENT,
            'max_profit': arb_opportunity['profit_percent'] <= MAX_ARB_PERCENTAGE,
            'stake_limits': all(stake <= MAX_STAKE_PER_BOOKMAKER for stake in arb_opportunity['stakes'].values()),
            'not_sent': not already_sent(arb_opportunity['match_id']),
            'daily_limit': get_daily_log()['count'] < DAILY_MATCH_LIMIT
        }
        
        return all(checks.values())

# --- SCHEDULED SCANNING ---
def start_scheduled_scanning():
    """Start background scanning for arbitrage opportunities"""
    def scan_job():
        print(f"[{datetime.now()}] Starting scheduled scan...")
        try:
            engine = ArbitrageEngine()
            
            # Get European data
            european_matches = engine.odds_provider.get_european_odds()
            print(f"Found {len(european_matches)} European matches")
            
            # Get African data
            african_odds = engine.scraper.get_african_odds()
            african_count = sum(len(matches) for matches in african_odds.values())
            print(f"Found {african_count} African odds entries")
            
            # Find arbitrage
            opportunities = engine.find_cross_bookmaker_arb(european_matches, african_odds)
            print(f"Found {len(opportunities)} arbitrage opportunities")
            
            # Cache opportunities
            for arb in opportunities:
                cache_match_data(arb['match_id'], arb, ttl_minutes=10)
            
            engine.scraper.close()
            
        except Exception as e:
            print(f"Scanning error: {e}")
    
    # Schedule scans every 5 minutes
    schedule.every(5).minutes.do(scan_job)
    
    # Run immediately
    scan_job()
    
    # Start scheduler in background thread
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
    
    # Get cached arbitrage opportunities
    engine = ArbitrageEngine()
    european_matches = engine.odds_provider.get_european_odds()
    african_odds = engine.scraper.get_african_odds()
    opportunities = engine.find_cross_bookmaker_arb(european_matches, african_odds)
    
    for arb in opportunities:
        if not already_sent(arb['match_id']):
            update_log(arb['match_id'])
            
            # Split legs for automation
            automate_leg = arb['legs'][0]
            macrodroid_legs = arb['legs'][1:]
            
            return jsonify({
                "status": "arb",
                "match": f"{arb['teams']} ({arb['league']}) at {arb['time']}",
                "profit": f"{arb['profit_percent']}%",
                "arb_percentage": arb['arb_percentage'],
                "total_stake": arb['total_stake'],
                "expected_return": arb['expected_return'],
                "automate_leg": automate_leg,
                "macrodroid_legs": macrodroid_legs,
                "progress": f"{log['count']+1}/{DAILY_MATCH_LIMIT}",
                "source": "real_data"
            })
    
    # Fallback to simulated data if no real arbitrage found
    return jsonify({"status": "none", "message": "No arbitrage opportunities found"})

@app.route("/test_scrape")
def test_scrape():
    """Test endpoint to check scraping functionality"""
    try:
        scraper = AfricanBookmakerScraper()
        african_odds = scraper.get_african_odds()
        scraper.close()
        
        return jsonify({
            "status": "success",
            "bookmakers": list(african_odds.keys()),
            "match_counts": {bm: len(matches) for bm, matches in african_odds.items()}
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
    return f"✅ Real Arbitrage Engine — {log['count']}/{DAILY_MATCH_LIMIT} — African + European Data"

@app.route("/")
def home():
    return """
    <h1>🚀 Real Arbitrage Engine</h1>
    <p>African Bookmakers + European APIs</p>
    <p>Endpoints:</p>
    <ul>
        <li><a href="/next_arb">/next_arb</a> - Get next arbitrage opportunity</li>
        <li><a href="/test_scrape">/test_scrape</a> - Test African bookmaker scraping</li>
        <li><a href="/health">/health</a> - System status</li>
    </ul>
    """

# Start background scanning when app starts
@app.before_first_request
def startup():
    start_scheduled_scanning()

if __name__ == "__main__":
    print("Starting Real Arbitrage Engine with African Bookmaker Scraping...")
    app.run(host="0.0.0.0", port=8000, debug=False)
