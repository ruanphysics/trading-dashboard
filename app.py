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
markets = ["bitcoin", "ethereum", "ripple", "solana"]
stake_levels = [4, 8, 16]
STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

# =========================
# TIMER
# =========================
def get_countdown():
    now = datetime.utcnow()
    seconds = now.minute * 60 + now.second
    remaining = 300 - (seconds % 300)
    return f"{remaining//60:02d}:{remaining%60:02d}", remaining

# =========================
# POLYMARKET (FIXED)
# =========================
def get_polymarket_price(asset):
    try:
        url = "https://gamma-api.polymarket.com/events"
        res = requests.get(url, timeout=5)

        if res.status_code != 200:
            return None

        data = res.json()

        prefix_map = {
            "bitcoin": "btc-updown-5m",
            "ethereum": "eth-updown-5m",
            "ripple": "xrp-updown-5m",
            "solana": "sol-updown-5m"
        }

        keyword = prefix_map[asset]

        for event in data:
            slug = event.get("slug", "")

            if keyword in slug:
                markets = event.get("markets", [])

                if markets:
                    outcomes = markets[0].get("outcomes", [])

                    if outcomes:
                        try:
                            price = float(outcomes[0]["price"])
                            if 0 < price < 1:
                                return price
                        except:
                            continue

        return None

    except Exception as e:
        print("POLY ERROR:", e)
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
        "history": [],
        "last_round_price": None,
        "current_price": None,
        "signal": None,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "bet": 0,
        "entry_price": None,
        "expected_profit": 0,
        "countdown": "--:--",
        "last_update": "Starting..."
    }

loaded = load_state()
state = loaded if loaded else default_state

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    last_cycle = None

    while True:
        try:
            time.sleep(5)

            countdown, _ = get_countdown()
            s["countdown"] = countdown

            price = get_polymarket_price(m)

            if price is None:
                s["last_update"] = "Waiting for market..."
                continue

            s["current_price"] = price
            current_cycle = int(time.time() // 300)

            if last_cycle is None:
                last_cycle = current_cycle
                s["last_round_price"] = price
                continue

            # NEW ROUND
            if current_cycle != last_cycle:

                if price > s["last_round_price"]:
                    outcome = "UP"
                elif price < s["last_round_price"]:
                    outcome = "DOWN"
                else:
                    outcome = "FLAT"

                if outcome != "FLAT":
                    s["history"].append(outcome)
                    if len(s["history"]) > 10:
                        s["history"].pop(0)

                # STRATEGY
                if len(s["history"]) >= 3:
                    last3 = s["history"][-3:]

                    if last3 == ["UP","UP","UP"]:
                        s["signal"] = "DOWN"
                    elif last3 == ["DOWN","DOWN","DOWN"]:
                        s["signal"] = "UP"
                    else:
                        s["signal"] = None

                # ENTER TRADE
                if s["signal"] and not s["in_trade"]:
                    s["in_trade"] = True
                    s["trade_direction"] = s["signal"]
                    s["step"] = 0

                # EXECUTE
                if s["in_trade"]:
                    bet = stake_levels[s["step"]]
                    entry_price = price

                    s["bet"] = bet
                    s["entry_price"] = entry_price
                    s["expected_profit"] = round(bet * (1 - entry_price), 2)

                    win = (
                        (s["trade_direction"] == "UP" and outcome == "UP") or
                        (s["trade_direction"] == "DOWN" and outcome == "DOWN")
                    )

                    if win:
                        profit = bet * (1 - entry_price)
                        with bankroll_lock:
                            bankroll += profit
                        s["profit"] += profit
                        s["in_trade"] = False
                    else:
                        loss = bet * entry_price
                        with bankroll_lock:
                            bankroll -= loss
                        s["profit"] -= loss
                        s["step"] += 1

                        if s["step"] >= len(stake_levels):
                            s["in_trade"] = False

                s["last_round_price"] = price
                last_cycle = current_cycle
                save_state()

            s["last_update"] = datetime.now().strftime("%H:%M:%S")

        except Exception as e:
            print("ERROR:", e)

# =========================
# START
# =========================
started = False

@app.before_request
def start_once():
    global started
    if not started:
        for m in markets:
            threading.Thread(target=run_market, args=(m,), daemon=True).start()
        started = True

# =========================
# UI
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Outcome Bot (Final)</h1>
<h2>Bank: ${{bankroll}}</h2>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>⏳ {{s.countdown}}</p>
<p>History: {{s.history}}</p>
<p>Signal: {{s.signal}}</p>
<p>Price: {{s.current_price}}</p>
<p>Last update: {{s.last_update}}</p>

{% if s.in_trade %}
<p>Trading {{s.trade_direction}} (step {{s.step+1}})</p>
<p>Bet: ${{s.bet}}</p>
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
    return render_template_string(HTML, state=state, bankroll=round(bankroll,2))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)