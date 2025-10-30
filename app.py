from flask import Flask, jsonify, request
import sqlite3, random, time
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIG ---
DAILY_MATCH_LIMIT = 12
STAKE_PER_ARB = 5250
MIN_PROFIT_PERCENT = 0.5


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
            match_id INTEGER PRIMARY KEY,
            sent_date TEXT
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
    con.commit()
    con.close()


# ---------------- ORIGINAL MATCH + ARB LOGIC (UNCHANGED) ------------------

def generate_massive_odds_data():
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

            base_home = round(random.uniform(1.8, 3.2), 2)
            base_draw = round(random.uniform(3.0, 4.0), 2)
            base_away = round(random.uniform(2.0, 3.8), 2)

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
                multiplier = random.uniform(0.95, 1.05)
                bookmaker_odds[bm] = {
                    "home": round(base_home * multiplier, 2),
                    "draw": round(base_draw * multiplier, 2),
                    "away": round(base_away * multiplier, 2)
                }

            hour = random.randint(8, 23)
            minute = random.choice([0, 15, 30, 45])
            match_time = f"{hour:02d}:{minute:02d}"

            matches.append({
                "id": match_id,
                "teams": f"{home} vs {away}",
                "league": league,
                "bookmaker_odds": bookmaker_odds,
                "time": match_time,
                "date": datetime.now().strftime("%Y-%m-%d")
            })

            match_id += 1
            if match_id > 150:
                break
    return matches


def find_best_arb(match_data):
    best_arb = None
    max_profit = 0
    bookmakers = list(match_data['bookmaker_odds'].keys())

    for bm_h in bookmakers:
        for bm_d in bookmakers:
            for bm_a in bookmakers:
                if len({bm_h, bm_d, bm_a}) == 3:
                    odds_h = match_data['bookmaker_odds'][bm_h]['home']
                    odds_d = match_data['bookmaker_odds'][bm_d]['draw']
                    odds_a = match_data['bookmaker_odds'][bm_a]['away']

                    arb_index = (1/odds_h + 1/odds_d + 1/odds_a)
                    if arb_index < 1.0:
                        profit_percent = ((1 / arb_index) - 1) * 100
                        if profit_percent > max_profit and profit_percent >= MIN_PROFIT_PERCENT:
                            stake_h = round((1/odds_h) * STAKE_PER_ARB / arb_index, 2)
                            stake_d = round((1/odds_d) * STAKE_PER_ARB / arb_index, 2)
                            stake_a = round((1/odds_a) * STAKE_PER_ARB / arb_index, 2)

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


# ---------------- ROUTES ----------------

@app.route("/next_arb")
def next_arb():
    log = get_daily_log()
    if log["count"] >= DAILY_MATCH_LIMIT:
        return jsonify({"status": "limit", "progress": f"{log['count']}/{DAILY_MATCH_LIMIT}"})

    matches = generate_massive_odds_data()

    for m in matches:
        if m["id"] > log["last_sent"] and not already_sent(m["id"]):
            arb = find_best_arb(m)
            if arb:
                update_log(m["id"])
                automate_leg = arb['legs'][0]
                md_legs = arb['legs'][1:]
                return jsonify({
                    "status": "arb",
                    "match": f"{arb['teams']} ({arb['league']}) at {arb['time']}",
                    "profit": f"{arb['profit_percent']}%",
                    "automate_leg": automate_leg,
                    "macrodroid_legs": md_legs,
                    "progress": f"{log['count']+1}/{DAILY_MATCH_LIMIT}"
                })

    return jsonify({"status": "none"})


@app.route("/reset", methods=["POST"])
def reset():
    reset_db()
    return jsonify({"reset": "ok"})


@app.route("/health")
def health():
    log = get_daily_log()
    return f"✅ Running — {log['count']}/{DAILY_MATCH_LIMIT]"


@app.route("/")
def home():
    return "🚀 Arbitrage Engine with DB — Ready"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
