import requests
import time
import threading
import json
import os
from datetime import datetime
import pytz
from flask import Flask, jsonify, render_template_string

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

ET = pytz.timezone("America/New_York")

# =========================
# TIME (ET ALIGNED)
# =========================
def get_et_timestamp():
    return int(datetime.now(ET).timestamp())

def get_round_times():
    now = get_et_timestamp()
    end = now - (now % 300)
    start = end - 300
    return start, end

def get_countdown_seconds():
    now = get_et_timestamp()
    return 300 - (now % 300)

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
# SIMPLE POLY PRICE (fallback = 0.5)
# =========================
def get_poly_price():
    try:
        url = "https://gamma-api.polymarket.com/events"
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return 0.5

        data = res.json()
        for e in data:
            markets = e.get("markets", [])
            if markets:
                outcomes = markets[0].get("outcomes", [])
                if outcomes:
                    p = float(outcomes[0]["price"])
                    if 0 < p < 1:
                        return p
        return 0.5
    except:
        return 0.5

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
        "current_price": None,
        "signal": None,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "bet": 0,
        "entry_price": None,
        "expected_profit": 0,
        "round": "",
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

    last_round_end = None

    while True:
        try:
            time.sleep(3)

            start, end = get_round_times()
            s["round"] = f"{datetime.fromtimestamp(start, ET).strftime('%H:%M')} → {datetime.fromtimestamp(end, ET).strftime('%H:%M')}"

            price = get_coinbase_price(symbols[m])

            if price is None:
                s["last_update"] = "No price"
                continue

            s["current_price"] = price

            if last_round_end is None:
                last_round_end = end
                s["start_price"] = price
                continue

            if end != last_round_end:
                end_price = price

                if end_price > s["start_price"]:
                    outcome = "UP"
                elif end_price < s["start_price"]:
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
                    entry_price = get_poly_price()

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

                s["start_price"] = price
                last_round_end = end
                save_state()

            s["last_update"] = datetime.now(ET).strftime("%H:%M:%S")

        except Exception as e:
            print("ERROR:", e)

# =========================
# START THREADS
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
# API ENDPOINT
# =========================
@app.route("/data")
def data():
    return jsonify({
        "state": state,
        "bankroll": round(bankroll, 2),
        "countdown": get_countdown_seconds()
    })

# =========================
# UI (SMOOTH)
# =========================
HTML = """
<html>
<head>
<script>
async function fetchData() {
    const res = await fetch('/data');
    const data = await res.json();

    document.getElementById("bank").innerText = data.bankroll;

    for (const [m, s] of Object.entries(data.state)) {
        document.getElementById(m+"_price").innerText = s.current_price ?? "-";
        document.getElementById(m+"_signal").innerText = s.signal ?? "-";
        document.getElementById(m+"_history").innerText = s.history.join(",");
        document.getElementById(m+"_round").innerText = s.round;
        document.getElementById(m+"_update").innerText = s.last_update;
    }
}

function countdownTick() {
    let el = document.getElementById("timer");
    let val = parseInt(el.dataset.seconds);
    val = (val - 1 + 300) % 300;
    el.dataset.seconds = val;
    let m = String(Math.floor(val/60)).padStart(2,'0');
    let s = String(val%60).padStart(2,'0');
    el.innerText = m + ":" + s;
}

async function init() {
    const res = await fetch('/data');
    const data = await res.json();
    document.getElementById("timer").dataset.seconds = data.countdown;

    setInterval(fetchData, 3000);
    setInterval(countdownTick, 1000);
}

window.onload = init;
</script>
</head>

<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Hybrid Bot (Smooth)</h1>
<h2>Bank: $<span id="bank">...</span></h2>

<h2>⏳ <span id="timer" data-seconds="0">--:--</span></h2>

{% for m in state %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>Round: <span id="{{m}}_round">-</span></p>
<p>Price: <span id="{{m}}_price">-</span></p>
<p>Signal: <span id="{{m}}_signal">-</span></p>
<p>History: <span id="{{m}}_history">-</span></p>
<p>Last update: <span id="{{m}}_update">-</span></p>

</div>
{% endfor %}

</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, state=state)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)