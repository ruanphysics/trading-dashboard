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
GAMMA_URL = "https://gamma-api.polymarket.com/markets"

BASE_BET = 1.0
TARGET_PROFIT = 0.30
MAX_BET = 5.0
MAX_STEPS = 10

ROUND_WAIT = 320
SLEEP_TIME = 10

MAX_MARKETS = 4

ET = pytz.timezone("US/Eastern")

bankroll = 100.0
market_states = {}

# =========================
# FLASK
# =========================
app = Flask(__name__)

TEMPLATE = """
<h1>📊 Multi-Market Simulation</h1>

<p><b>Total Bankroll:</b> {{bankroll}}</p>

{% for m in markets %}
<div style="border:1px solid #ccc; padding:10px; margin:10px;">
<b>{{m['question']}}</b><br>

Price: {{m['price']}}<br>
Status: {{m['status']}}<br>
Bet: {{m['bet']}}<br>
Profit: {{m['profit']}}<br>
Step: {{m['step']}}<br>
Loss: {{m['loss']}}<br>

<br>
<b>⏱ Round Info (ET)</b><br>
Current Time: {{m['et_time']}}<br>
Round Ends In: {{m['timer']}}<br>

<br>
<b>Outcome History:</b> {{m['history']}}<br>
<b>Price Trend:</b> {{m['price_history']}}
</div>
{% endfor %}
"""

@app.route("/")
def home():
    display = []

    for mid, s in market_states.items():
        status = "Waiting for pattern" if not s["active_trade"] else f"Betting {s['side']}"

        et_now, timer = get_round_timer()

        display.append({
            "question": s["question"],
            "price": round(s.get("price", 0), 3),
            "status": status,
            "bet": round(s.get("bet", 0), 2),
            "profit": round(s.get("profit", 0), 2),
            "step": s.get("step", 1),
            "loss": round(s.get("loss", 0), 2),
            "history": s.get("history", []),
            "price_history": [round(p, 3) for p in s.get("history_prices", [])],
            "et_time": et_now,
            "timer": timer
        })

    return render_template_string(
        TEMPLATE,
        bankroll=round(bankroll, 2),
        markets=display
    )

# =========================
# TIME
# =========================
def get_round_timer():
    now = datetime.now(ET)

    minute = (now.minute // 5) * 5
    round_start = now.replace(minute=minute, second=0, microsecond=0)
    next_round = round_start + timedelta(minutes=5)

    remaining = next_round - now
    seconds = int(remaining.total_seconds())

    mins = seconds // 60
    secs = seconds % 60

    return now.strftime("%H:%M:%S"), f"{mins:02d}:{secs:02d}"

# =========================
# MARKET FILTER (SMART)
# =========================
def find_markets(markets):
    selected = []

    for m in markets:
        q = m["question"].lower()

        # SMART FILTER:
        # - Must mention time window (5 min / 5 minutes)
        # - Must be crypto (BTC / ETH)
        # - Avoid weird/long-term markets
        if (
            ("5" in q and "min" in q)
            and ("btc" in q or "eth" in q)
        ):
            selected.append(m)

        if len(selected) >= MAX_MARKETS:
            break

    return selected

# =========================
# HELPERS
# =========================
def get_active_markets():
    return requests.get(GAMMA_URL, params={"active": "true", "limit": 100}).json()

def extract_tokens(market):
    tokens = {}
    for o in market["outcomes"]:
        name = o["name"].lower()
        if "up" in name or "yes" in name:
            tokens["UP"] = o["token_id"]
        elif "down" in name or "no" in name:
            tokens["DOWN"] = o["token_id"]
    return tokens

def get_price(token_id):
    try:
        url = f"https://clob.polymarket.com/books/{token_id}"
        data = requests.get(url).json()
        asks = data.get("asks", [])
        if not asks:
            return None
        return float(asks[0]["price"])
    except:
        return None

def get_result(market_id):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}").json()
        for o in data["outcomes"]:
            if o.get("winner"):
                name = o["name"].lower()
                return "UP" if "up" in name or "yes" in name else "DOWN"
    except:
        return None
    return None

# =========================
# STRATEGY
# =========================
def detect_streak(history):
    if len(history) < 4:
        return None

    dirs = []
    for i in range(1, len(history)):
        dirs.append("UP" if history[i] > history[i-1] else "DOWN")

    last3 = dirs[-3:]

    if all(d == "DOWN" for d in last3):
        return "UP"
    if all(d == "UP" for d in last3):
        return "DOWN"

    return None

def calculate_bet(price, state):
    if price <= 0 or price >= 1:
        return BASE_BET

    required = state["loss"] + TARGET_PROFIT
    raw = required * (price / (1 - price))

    return max(min(raw, MAX_BET), BASE_BET)

# =========================
# BOT LOOP
# =========================
def run_bot():
    global bankroll

    print("🚀 Multi-market bot started...")

    while True:
        try:
            markets = get_active_markets()
            selected = find_markets(markets)

            print("Markets found:", len(selected))  # DEBUG

            for m in selected:
                mid = m["id"]

                if mid not in market_states:
                    market_states[mid] = {
                        "question": m["question"],
                        "history_prices": [],
                        "history": [],
                        "loss": 0,
                        "step": 1,
                        "active_trade": False,
                        "side": None,
                        "bet": 0,
                        "profit": 0,
                        "last_trade_time": 0
                    }

                state = market_states[mid]
                tokens = extract_tokens(m)

                price = get_price(tokens["UP"])
                if not price:
                    continue

                state["price"] = price
                state["history_prices"].append(price)

                if len(state["history_prices"]) > 5:
                    state["history_prices"].pop(0)

                if not state["active_trade"]:
                    signal = detect_streak(state["history_prices"])
                    if signal:
                        state["active_trade"] = True
                        state["side"] = signal

                if state["active_trade"]:
                    if time.time() - state["last_trade_time"] < ROUND_WAIT:
                        continue

                    trade_price = get_price(tokens[state["side"]])
                    if not trade_price:
                        continue

                    bet = calculate_bet(trade_price, state)

                    state["bet"] = bet
                    state["last_trade_time"] = time.time()

                    result = get_result(mid)
                    if not result:
                        continue

                    state["history"].append(result)
                    if len(state["history"]) > 15:
                        state["history"].pop(0)

                    if result == state["side"]:
                        profit = bet * ((1 - trade_price) / trade_price)
                        bankroll += profit
                        state["profit"] += profit

                        state["loss"] = 0
                        state["step"] = 1
                        state["active_trade"] = False
                    else:
                        bankroll -= bet
                        state["loss"] += bet
                        state["step"] += 1

                        if state["step"] > MAX_STEPS:
                            state["loss"] = 0
                            state["step"] = 1
                            state["active_trade"] = False

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))