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

# NEW LADDER
stake_levels = [4, 8, 20, 44, 100]

STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

ET = pytz.timezone("America/New_York")
START_TIME = time.time()

# =========================
# TIME
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

def get_uptime():
    seconds = int(time.time() - START_TIME)
    return time.strftime("%H:%M:%S", time.gmtime(seconds))

# =========================
# PRICE
# =========================
def get_coinbase_price(symbol):
    try:
        url = f"https://api.exchange.coinbase.com/products/{symbol}/ticker"
        res = requests.get(url, timeout=5).json()
        return float(res["price"])
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
        "current_price": None,
        "signal": None,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "bet": 0,
        "pending": False,
        "waiting_for_pattern": False,
        "last_processed_end": None,
        "round": "",
        "countdown": 0,
        "max_streak": 0
    }

loaded = load_state()
state = loaded if loaded else default_state

# =========================
# STREAK
# =========================
def get_streak(history):
    if not history:
        return None, 0
    last = history[-1]
    count = 1
    for i in range(len(history)-2, -1, -1):
        if history[i] == last:
            count += 1
        else:
            break
    return last, count

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]
    last_round_end = None

    while True:
        try:
            time.sleep(1)

            start, end = get_round_times()

            s["round"] = f"{datetime.fromtimestamp(start, ET).strftime('%H:%M')} → {datetime.fromtimestamp(end, ET).strftime('%H:%M')}"
            s["countdown"] = get_countdown_seconds()

            price = get_coinbase_price(symbols[m])
            if price is None:
                continue

            s["current_price"] = price

            if last_round_end is None:
                last_round_end = end
                s["start_price"] = price
                continue

            if s["last_processed_end"] == end:
                continue

            if end > last_round_end:
                s["last_processed_end"] = end
                s["pending"] = False

                # OUTCOME
                if price > s["start_price"]:
                    outcome = "UP"
                elif price < s["start_price"]:
                    outcome = "DOWN"
                else:
                    outcome = "FLAT"

                if outcome != "FLAT":
                    s["history"].append(outcome)
                    if len(s["history"]) > 7:
                        s["history"].pop(0)

                # STREAK
                streak_dir, streak_count = get_streak(s["history"])

                # UPDATE MAX STREAK
                if streak_count > s["max_streak"]:
                    s["max_streak"] = streak_count

                # SIGNAL
                if streak_count >= 3:
                    s["signal"] = "DOWN" if streak_dir == "UP" else "UP"
                else:
                    s["signal"] = None

                # UNLOCK WAIT
                if s["waiting_for_pattern"] and s["signal"]:
                    s["waiting_for_pattern"] = False

                # =========================
                # EXECUTE
                # =========================
                if s["in_trade"]:
                    prev_bet = stake_levels[s["step"]]

                    win = (
                        (s["trade_direction"] == "UP" and outcome == "UP") or
                        (s["trade_direction"] == "DOWN" and outcome == "DOWN")
                    )

                    if win:
                        profit = prev_bet * 0.75
                        with bankroll_lock:
                            bankroll += profit
                        s["profit"] += profit

                        # RESET
                        s["in_trade"] = False
                        s["waiting_for_pattern"] = True
                        s["trade_direction"] = None
                        s["step"] = 0

                        s["history"] = []
                        s["signal"] = None
                        s["pending"] = False
                        s["max_streak"] = 0

                    else:
                        loss = prev_bet
                        with bankroll_lock:
                            bankroll -= loss
                        s["profit"] -= loss

                        s["step"] += 1

                        if s["step"] >= len(stake_levels):
                            # FINAL LOSS RESET
                            s["in_trade"] = False
                            s["waiting_for_pattern"] = True
                            s["trade_direction"] = None
                            s["step"] = 0

                            s["history"] = []
                            s["signal"] = None
                            s["pending"] = False
                            s["max_streak"] = 0
                        else:
                            s["pending"] = True

                # ENTER TRADE
                if s["signal"] and not s["in_trade"] and not s["waiting_for_pattern"]:
                    s["in_trade"] = True
                    s["trade_direction"] = s["signal"]
                    s["step"] = 0
                    s["bet"] = stake_levels[0]
                    s["pending"] = True

                # UPDATE BET
                if s["in_trade"]:
                    s["bet"] = stake_levels[s["step"]]

                s["start_price"] = price
                last_round_end = end
                save_state()

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
# API
# =========================
@app.route("/data")
def data():
    return jsonify({
        "state": state,
        "bankroll": round(bankroll, 2),
        "uptime": get_uptime()
    })

# =========================
# UI
# =========================
HTML = """
<html>
<head>
<script>
function formatHistory(arr){
    return arr.map(x => x === "UP"
        ? '<span style="color:#22c55e">UP</span>'
        : '<span style="color:#ef4444">DOWN</span>'
    ).join(", ");
}

async function fetchData() {
    const res = await fetch('/data');
    const data = await res.json();

    document.getElementById("bank").innerText = data.bankroll;
    document.getElementById("uptime").innerText = data.uptime;

    for (const [m, s] of Object.entries(data.state)) {

        document.getElementById(m+"_history").innerHTML = formatHistory(s.history);
        document.getElementById(m+"_signal").innerText = s.signal ?? "-";
        document.getElementById(m+"_round").innerText = s.round;

        document.getElementById(m+"_streak").innerText = s.max_streak ?? 0;

        let sec = s.countdown;
        let min = String(Math.floor(sec/60)).padStart(2,'0');
        let s2 = String(sec%60).padStart(2,'0');
        document.getElementById(m+"_timer").innerText = min + ":" + s2;

        if(s.waiting_for_pattern){
            document.getElementById(m+"_trade").innerText = "Waiting for pattern";
        }
        else if(s.in_trade){
            document.getElementById(m+"_trade").innerText =
                s.trade_direction + " | $" + s.bet + " | Step " + (s.step+1);
        } else {
            document.getElementById(m+"_trade").innerText = "None";
        }

        if(s.pending){
            document.getElementById(m+"_profit").innerText =
                "Pending (internal: $" + s.profit.toFixed(2) + ")";
        } else {
            document.getElementById(m+"_profit").innerText =
                "$" + s.profit.toFixed(2);
        }
    }
}

setInterval(fetchData, 2000);
</script>
</head>

<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Hybrid Bot (Final)</h1>
<h2>Bank: $<span id="bank">...</span></h2>

<div style="position:fixed;top:10px;right:20px;color:#94a3b8">
Uptime: <span id="uptime">00:00:00</span>
</div>

{% for m in state %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>Round: <span id="{{m}}_round">-</span></p>
<p>⏳ <span id="{{m}}_timer">--:--</span></p>

<p>Signal: <span id="{{m}}_signal">-</span></p>
<p>History: <span id="{{m}}_history">-</span></p>

<p>Max Streak: <span id="{{m}}_streak">0</span></p>

<p>Active Bet: <span id="{{m}}_trade">None</span></p>
<p>Profit: <span id="{{m}}_profit">0</span></p>

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