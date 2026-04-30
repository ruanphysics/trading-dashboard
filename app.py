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
markets = ["bitcoin", "ethereum", "ripple", "solana"]
symbols = {
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
# TIMER (ALIGNED)
# =========================
def get_round_times():
    now = int(time.time())
    end = now - (now % 300)
    start = end - 300
    return start, end

def get_countdown():
    now = int(time.time())
    remaining = 300 - (now % 300)
    return f"{remaining//60:02d}:{remaining%60:02d}", remaining

# =========================
# COINBASE PRICE
# =========================
def get_coinbase_price(symbol):
    try:
        url = f"https://api.exchange.coinbase.com/products/{symbol}/ticker"
        res = requests.get(url, timeout=5).json()
        return float(res["price"])
    except:
        return None

# =========================
# POLYMARKET PRICE (OPTIONAL)
# =========================
def get_poly_price():
    try:
        url = "https://gamma-api.polymarket.com/events"
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return None

        data = res.json()
        for e in data:
            markets = e.get("markets", [])
            if markets:
                outcomes = markets[0].get("outcomes", [])
                if outcomes:
                    p = float(outcomes[0]["price"])
                    if 0 < p < 1:
                        return p
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
        "history": [],
        "start_price": None,
        "end_price": None,
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
        "last_update": "Starting...",
        "round": "",
    }

loaded = load_state()
state = loaded if loaded else default_state

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    last_round_end = None

    while True:
        try:
            time.sleep(5)

            countdown, _ = get_countdown()
            s["countdown"] = countdown

            start, end = get_round_times()
            s["round"] = f"{datetime.utcfromtimestamp(start).strftime('%H:%M')} → {datetime.utcfromtimestamp(end).strftime('%H:%M')}"

            price = get_coinbase_price(symbols[m])

            if price is None:
                s["last_update"] = "No Coinbase data"
                continue

            s["current_price"] = price

            # FIRST INIT
            if last_round_end is None:
                last_round_end = end
                s["start_price"] = price
                continue

            # NEW ROUND DETECTED
            if end != last_round_end:
                s["end_price"] = price

                # DETERMINE OUTCOME
                if s["end_price"] > s["start_price"]:
                    outcome = "UP"
                elif s["end_price"] < s["start_price"]:
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

                # EXECUTE TRADE
                if s["in_trade"]:
                    bet = stake_levels[s["step"]]
                    entry_price = get_poly_price() or 0.5

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

                # RESET FOR NEXT ROUND
                s["start_price"] = price
                last_round_end = end

                save_state()

            s["last_update"] = datetime.utcnow().strftime("%H:%M:%S")

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

<h1>Hybrid Bot (Stable)</h1>
<h2>Bank: ${{bankroll}}</h2>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>Round: {{s.round}}</p>
<p>⏳ {{s.countdown}}</p>
<p>Start: {{s.start_price}}</p>
<p>Current: {{s.current_price}}</p>

<p>History: {{s.history}}</p>
<p>Signal: {{s.signal}}</p>
<p>Last update: {{s.last_update}}</p>

{% if s.in_trade %}
<p>Trading {{s.trade_direction}} (step {{s.step+1}})</p>
<p>Bet: ${{s.bet}}</p>
<p>Entry price: {{s.entry_price}}</p>
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