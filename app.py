import requests
import time
import threading
import json
import os
from datetime import datetime
from flask import Flask, render_template_string

# =========================
# SETTINGS
# =========================
markets = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "ripple": "XRP-USD",
    "solana": "SOL-USD"
}

stake_levels = [4, 8, 16]
STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

# =========================
# TIMER (5-MIN CYCLE)
# =========================
def get_countdown():
    now = datetime.utcnow()
    seconds = now.minute * 60 + now.second
    remaining = 300 - (seconds % 300)

    mins = remaining // 60
    secs = remaining % 60

    return f"{mins:02d}:{secs:02d}"

# =========================
# COINBASE PRICE
# =========================
def get_coinbase_price(pair):
    try:
        url = f"https://api.exchange.coinbase.com/products/{pair}/ticker"
        res = requests.get(url, timeout=10).json()
        return float(res["price"])
    except:
        return None

# =========================
# POLYMARKET PRICE
# =========================
def get_polymarket_price(asset):
    try:
        url = "https://gamma-api.polymarket.com/markets"
        res = requests.get(url, timeout=10).json()

        asset_map = {
            "bitcoin": ["bitcoin", "btc"],
            "ethereum": ["ethereum", "eth"],
            "ripple": ["ripple", "xrp"],
            "solana": ["solana", "sol"]
        }

        keywords = asset_map[asset]

        for m in res:
            title = m.get("question", "").lower()

            if any(k in title for k in keywords) and m.get("active", True):
                outcomes = m.get("outcomes", [])
                if outcomes:
                    price = float(outcomes[0]["price"])
                    if 0 < price < 1:
                        return price

        return None
    except:
        return None

# =========================
# SAVE / LOAD
# =========================
def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"bankroll": bankroll, "state": state}, f)
    except:
        pass

def load_state():
    global bankroll
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                bankroll = data.get("bankroll", 100)
                return data.get("state", {})
        except:
            pass
    return None

# =========================
# STATE
# =========================
default_state = {}
for m in markets:
    default_state[m] = {
        "up_streak": 0,
        "down_streak": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "entry_price": None,
        "current_bet": 0,
        "expected_profit": 0,
        "last_price": None,
        "last_update": "Starting...",
        "poly_price": None,
        "countdown": "--:--"
    }

loaded = load_state()
state = loaded if loaded else default_state

# =========================
# BOT
# =========================
def run_market(m, pair):
    global bankroll
    s = state[m]

    print(f"STARTED BOT: {m}")

    while True:
        try:
            time.sleep(60)

            price = get_coinbase_price(pair)
            poly_price = get_polymarket_price(m)

            if price is None or poly_price is None:
                s["last_update"] = "No data"
                continue

            s["poly_price"] = poly_price
            s["countdown"] = get_countdown()

            if s["last_price"] is None:
                s["last_price"] = price
                continue

            s["last_update"] = datetime.now().strftime("%H:%M:%S")

            # STREAK
            if price > s["last_price"]:
                s["up_streak"] += 1
                s["down_streak"] = 0
            elif price < s["last_price"]:
                s["down_streak"] += 1
                s["up_streak"] = 0

            s["last_price"] = price

            # ENTRY
            if not s["in_trade"]:
                if s["up_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "DOWN"
                    s["step"] = 0

                elif s["down_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "UP"
                    s["step"] = 0

            # TRADE LOOP
            while s["in_trade"] and s["step"] < len(stake_levels):
                bet = stake_levels[s["step"]]
                entry_price = s["poly_price"]

                s["current_bet"] = bet
                s["entry_price"] = entry_price
                s["expected_profit"] = round(bet * (1 - entry_price), 2)

                time.sleep(300)

                new_price = get_coinbase_price(pair)

                if new_price is None:
                    continue

                win = False
                if s["trade_direction"] == "DOWN" and new_price < s["last_price"]:
                    win = True
                elif s["trade_direction"] == "UP" and new_price > s["last_price"]:
                    win = True

                if win:
                    profit = bet * (1 - entry_price)
                    with bankroll_lock:
                        bankroll += profit

                    s["profit"] += profit
                    s["in_trade"] = False
                    s["up_streak"] = 0
                    s["down_streak"] = 0
                    break

                else:
                    loss = bet * entry_price
                    with bankroll_lock:
                        bankroll -= loss

                    s["profit"] -= loss
                    s["step"] += 1

            if s["in_trade"] and s["step"] >= len(stake_levels):
                s["in_trade"] = False
                s["up_streak"] = 0
                s["down_streak"] = 0

            save_state()

        except Exception as e:
            print("THREAD ERROR:", e)

# =========================
# START
# =========================
bots_started = False

@app.before_request
def start_once():
    global bots_started
    if not bots_started:
        print("🔥 STARTING BOTS...")
        for m, pair in markets.items():
            threading.Thread(target=run_market, args=(m, pair), daemon=True).start()
        bots_started = True

# =========================
# UI
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Hybrid Bot</h1>
<h2>Bank: ${{bankroll}}</h2>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>⏳ {{s.countdown}}</p>
<p>U:{{s.up_streak}} D:{{s.down_streak}}</p>
<p>Coinbase: {{s.last_price}}</p>
<p>Polymarket: {{s.poly_price}}</p>
<p>Last update: {{s.last_update}}</p>

{% if s.in_trade %}
<p>Trading {{s.trade_direction}} (step {{s.step+1}})</p>
<p>Bet: ${{s.current_bet}}</p>
<p>Expected profit: ${{s.expected_profit}}</p>
{% else %}
<p>Idle</p>
{% endif %}

<p>Profit: {{s.profit}}</p>
</div>
{% endfor %}

</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(
        HTML,
        state=state,
        bankroll=round(bankroll, 2)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)