import requests
import time
import threading
import json
import os
from datetime import datetime, timezone
from flask import Flask, render_template_string

# =========================
# SETTINGS
# =========================
markets = ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD"]
stake_levels = [4, 8, 16]

STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

# =========================
# LOAD / SAVE
# =========================
def save_state():
    data = {
        "bankroll": bankroll,
        "state": state
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def load_state():
    global bankroll, state

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
        "entry_time": None,
        "current_bet": 0,
        "expected_profit": 0,
        "last_update": "Starting..."
    }

loaded = load_state()

if loaded:
    state = loaded
else:
    state = default_state

# =========================
# TIME
# =========================
def wait_for_next_candle():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    return 300 - (seconds % 300)

def get_countdown():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    remaining = 300 - (seconds % 300)
    return f"{remaining//60:02d}:{remaining%60:02d}"

# =========================
# DATA
# =========================
def get_last_two_closes(market):
    try:
        url = f"https://api.exchange.coinbase.com/products/{market}/candles?granularity=300"
        data = requests.get(url, timeout=10).json()

        if len(data) < 2:
            return None, None

        return data[1][4], data[0][4]

    except Exception as e:
        print("API ERROR:", e)
        return None, None

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    print(f"STARTED BOT: {m}")

    while True:
        try:
            wait = wait_for_next_candle()
            time.sleep(wait + 2)

            prev_close, last_close = get_last_two_closes(m)

            if prev_close is None:
                s["last_update"] = "No data"
                continue

            s["last_update"] = datetime.now().strftime("%H:%M:%S")

            # STREAK
            if last_close > prev_close:
                s["up_streak"] += 1
                s["down_streak"] = 0
            else:
                s["down_streak"] += 1
                s["up_streak"] = 0

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

                s["current_bet"] = bet
                s["expected_profit"] = bet * 0.75

                wait = wait_for_next_candle()
                time.sleep(wait + 2)

                prev_close, new_close = get_last_two_closes(m)

                win = False
                if s["trade_direction"] == "DOWN" and new_close < prev_close:
                    win = True
                elif s["trade_direction"] == "UP" and new_close > prev_close:
                    win = True

                if win:
                    profit = bet * 0.75
                    with bankroll_lock:
                        bankroll += profit

                    s["profit"] += profit
                    s["in_trade"] = False
                    s["up_streak"] = 0
                    s["down_streak"] = 0
                    break

                else:
                    with bankroll_lock:
                        bankroll -= bet

                    s["profit"] -= bet
                    s["step"] += 1

            if s["in_trade"] and s["step"] >= len(stake_levels):
                s["in_trade"] = False
                s["up_streak"] = 0
                s["down_streak"] = 0

            # 💾 SAVE EVERY LOOP
            save_state()

        except Exception as e:
            print("THREAD ERROR:", e)

# =========================
# START BOTS
# =========================
bots_started = False

@app.before_request
def start_once():
    global bots_started
    if not bots_started:
        print("🔥 STARTING BOTS...")
        for m in markets:
            threading.Thread(target=run_market, args=(m,), daemon=True).start()
        bots_started = True

# =========================
# UI
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="3"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Dashboard</h1>
<h2>Bank: ${{bankroll}}</h2>
<h3>Next Candle: {{countdown}}</h3>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>
<p>U:{{s.up_streak}} D:{{s.down_streak}}</p>
<p>Last update: {{s.last_update}}</p>
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
        bankroll=round(bankroll, 2),
        countdown=get_countdown()
    )