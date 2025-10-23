from flask import Flask, jsonify
import time
from threading import Thread
import requests

app = Flask(__name__)

def get_mock_odds():
    return {
        "matches": [
            {
                "id": 1,
                "teams": "Rivers United vs Enyimba",
                "odds": {"home": 2.40, "draw": 3.60, "away": 4.50},
                "bookmakers": ["Bet9ja", "1xBet", "SportyBet"]
            },
            {
                "id": 2, 
                "teams": "Kano Pillars vs Rangers", 
                "odds": {"home": 2.10, "draw": 3.20, "away": 3.80},
                "bookmakers": ["BetKing", "NairaBet", "MerryBet"]
            }
        ]
    }

@app.route('/odds')
def get_odds():
    return jsonify({
        "odds": get_mock_odds(),
        "timestamp": time.time(),
        "status": "success"
    })

@app.route('/health')
def health():
    return "✅ Arbitrage API Running"

# Keep-alive to prevent Render sleep
def keep_alive():
    while True:
        try:
            requests.get("https://your-service.onrender.com/health")
        except:
            pass
        time.sleep(300)

Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
