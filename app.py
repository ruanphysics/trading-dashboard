import time
import requests
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime, timedelta
import pytz

# =========================
# CONFIG
# =========================
ASSETS = ["btc", "eth", "sol", "xrp"]

BASE_BET = 1.0
TARGET_PROFIT = 0.30
MAX_BET = 5.0
MAX_STEPS = 10

ROUND_SECONDS = 300
SLEEP_TIME = 10

ET = pytz.timezone("US/Eastern")

# =========================
# STATE
# =========================
bankroll = 100.0
market_states = {}
bot_started = False

# =========================
# FLASK
# =========================
app = Flask(__name__)

TEMPLATE = """
<h1>📊 5-Min Market Bot (Live Simulation)</h1>

<p><b>Bankroll:</b> {{bankroll}}</p>

{% for m in markets %}
<div style="border:1px solid #ccc; padding:10px; margin:10px;">
<b>{{m['name']}}</b><br>

Market ID: {{m['id']}}<br>
Price: {{m['price']}}<br>
Status: {{m['status']}}<br>
Bet: {{m['bet']}}<br>
Profit: {{m['profit']}}<br>
Step: {{m['step']}}<br>
Loss: {{m['loss']}}<br>

<br>
<b>⏱ Time (ET)</b><br>
Now: {{m['et_time']}}<br>
Ends In: {{m['timer']}}<br>

<br>
<b>History:</b> {{m['history']}}<br>
<b>Price Trend:</b> {{m['prices']}}
</div>
{% endfor %}
"""

@app.before_request
def start_bot():
    global bot_started
    if not bot_started:
        print("🚀 BOT STARTING")
        threading.Thread(target=run_bot, daemon=True).start()
        bot_started = True

@app.route("/")
def home():
    display = []

    for s in market_states.values():
        status = "Waiting for pattern" if not s["active"] else f"Betting {s['side']}"
        et_now, timer = get_timer()

        display.append({
            "name": s["name"],
            "id": s["id"],
            "price": round(s.get("price", 0), 3),
            "status": status,
            "bet": round(s.get("bet", 0), 2),
            "profit": round(s.get("profit", 0), 2),
            "step": s.get("step", 1),
            "loss": round(s.get("loss", 0), 2),
            "history": s.get("history", []),
            "prices": [round(p, 3) for p in s.get("prices", [])],
            "et_time": et_now,
            "timer": timer
        })

    return render_template_string(TEMPLATE, bankroll=round(bankroll, 2), markets=display)

# =========================
# TIME
# =========================
def get_timer():
    now = datetime.now(ET)
    rounded = now - timedelta(seconds=now.second % 300, microseconds=now.microsecond)
    next_round = rounded + timedelta(minutes=5)

    remaining = int((next_round - now).total_seconds())
    return now.strftime("%H:%M:%S"), f"{remaining//60:02d}:{remaining%60:02d}"

def generate_market_ids():
    now = int(time.time())
    base = now - (now % ROUND_SECONDS)

    ids = []
    for offset in [0, -300]:  # current + previous
        ts = base + offset
        for a in ASSETS:
            ids.append((a.upper(), f"{a}-updown-5m-{ts}"))

    return ids

# =========================
# PRICE / RESULT
# =========================
def get_tokens(market_id):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}").json()
        tokens = {}
        for o in data.get("outcomes", []):
            name = o["name"].lower()
            if "up" in name or "yes" in name:
                tokens["UP"] = o["token_id"]
            elif "down" in name or "no" in name:
                tokens["DOWN"] = o["token_id"]
        return tokens
    except:
        return {}

def get_price(token):
    try:
        data = requests.get(f"https://clob.polymarket.com/books/{token}").json()
        asks = data.get("asks", [])
        if asks:
            return float(asks[0]["price"])
    except:
        pass
    return None

def get_result(market_id):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}").json()
        for o in data.get("outcomes", []):
            if o.get("winner"):
                return "UP" if "up" in o["name"].lower() else "DOWN"
    except:
        pass
    return None

# =========================
# STRATEGY
# =========================
def detect_streak(prices):
    if len(prices) < 4:
        return None

    dirs = ["UP" if prices[i] > prices[i-1] else "DOWN" for i in range(1, len(prices))]
    last3 = dirs[-3:]

    if all(d == "DOWN" for d in last3):
        return "UP"
    if all(d == "UP" for d in last3):
        return "DOWN"

    return None

def calc_bet(price, state):
    if not price or price <= 0 or price >= 1:
        return BASE_BET

    required = state["loss"] + TARGET_PROFIT
    raw = required * (price / (1 - price))

    return max(min(raw, MAX_BET), BASE_BET)

# =========================
# BOT LOOP
# =========================
def run_bot():
    global bankroll

    while True:
        try:
            ids = generate_market_ids()

            for name, mid in ids:
                if mid not in market_states:
                    market_states[mid] = {
                        "name": f"{name} 5m",
                        "id": mid,
                        "prices": [],
                        "history": [],
                        "loss": 0,
                        "step": 1,
                        "active": False,
                        "side": None,
                        "bet": 0,
                        "profit": 0,
                        "last_trade": 0
                    }

                s = market_states[mid]

                tokens = get_tokens(mid)
                if "UP" not in tokens:
                    continue

                price = get_price(tokens["UP"])
                if not price:
                    continue

                s["price"] = price
                s["prices"].append(price)

                if len(s["prices"]) > 5:
                    s["prices"].pop(0)

                if not s["active"]:
                    signal = detect_streak(s["prices"])
                    if signal:
                        print(f"🔥 {name} SIGNAL {signal}")
                        s["active"] = True
                        s["side"] = signal

                if s["active"]:
                    if time.time() - s["last_trade"] < ROUND_SECONDS:
                        continue

                    trade_price = get_price(tokens[s["side"]])
                    if not trade_price:
                        continue

                    bet = calc_bet(trade_price, s)
                    s["bet"] = bet
                    s["last_trade"] = time.time()

                    result = get_result(mid)
                    if not result:
                        continue

                    s["history"].append(result)

                    if result == s["side"]:
                        profit = bet * ((1 - trade_price) / trade_price)
                        bankroll += profit
                        s["profit"] += profit
                        print(f"✅ {name} WIN {profit:.2f}")

                        s["loss"] = 0
                        s["step"] = 1
                        s["active"] = False
                    else:
                        bankroll -= bet
                        s["loss"] += bet
                        s["step"] += 1
                        print(f"❌ {name} LOSS {bet:.2f}")

                        if s["step"] > MAX_STEPS:
                            s["loss"] = 0
                            s["step"] = 1
                            s["active"] = False

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print("🔥 ERROR:", e)
            time.sleep(5)

# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))