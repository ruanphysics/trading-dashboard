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
<h1>📊 Multi-Market Simulation</h1>

<p><b>Total Bankroll:</b> {{bankroll}}</p>
<p><b>Markets Loaded:</b> {{count}}</p>

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
Time: {{m['et_time']}}<br>
Ends In: {{m['timer']}}<br>

<br>
<b>Outcome History:</b> {{m['history']}}<br>
<b>Price Trend:</b> {{m['price_history']}}
</div>
{% endfor %}
"""

# =========================
# START BOT (GUNICORN SAFE)
# =========================
@app.before_request
def start_bot_once():
    global bot_started
    if not bot_started:
        print("🚀 STARTING BOT THREAD")
        threading.Thread(target=run_bot, daemon=True).start()
        bot_started = True

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
        markets=display,
        count=len(display)
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
# API
# =========================
def get_active_markets():
    try:
        res = requests.get(GAMMA_URL, params={"active": "true", "limit": 100})
        data = res.json()

        print("📦 Markets fetched:", len(data))
        return data

    except Exception as e:
        print("❌ API ERROR:", e)
        return []

# =========================
# FINAL TARGETED FILTER
# =========================
def find_markets(markets):
    targets = ["btc", "eth", "sol", "xrp"]
    selected = []

    for m in markets:
        q = m.get("question", "").lower()

        if "up or down" not in q:
            continue

        if "5m" not in q and "5 min" not in q:
            continue

        if not any(t in q for t in targets):
            continue

        selected.append(m)

        if len(selected) >= MAX_MARKETS:
            break

    if not selected:
        print("⚠️ No matching Up/Down markets found")
    else:
        print("🎯 PERFECT MATCH MARKETS:")
        for s in selected:
            print(" -", s.get("question"))

    return selected

# =========================
# HELPERS
# =========================
def extract_tokens(market):
    tokens = {}
    for o in market.get("outcomes", []):
        name = o.get("name", "").lower()
        if "up" in name or "yes" in name:
            tokens["UP"] = o.get("token_id")
        elif "down" in name or "no" in name:
            tokens["DOWN"] = o.get("token_id")
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
        for o in data.get("outcomes", []):
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

    print("🚀 BOT STARTED")

    while True:
        try:
            markets = get_active_markets()

            if not markets:
                time.sleep(5)
                continue

            selected = find_markets(markets)

            if not selected:
                time.sleep(5)
                continue

            for m in selected:
                mid = m.get("id")
                if not mid:
                    continue

                if mid not in market_states:
                    print("➕ Adding market:", m.get("question"))
                    market_states[mid] = {
                        "question": m.get("question"),
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

                if "UP" not in tokens:
                    continue

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
                        print("🔥 SIGNAL:", signal)
                        state["active_trade"] = True
                        state["side"] = signal

                if state["active_trade"]:
                    if time.time() - state["last_trade_time"] < ROUND_WAIT:
                        continue

                    trade_price = get_price(tokens[state["side"]])
                    if not trade_price:
                        continue

                    bet = calculate_bet(trade_price, state)

                    print(f"🧪 BET {state['side']} ${bet:.2f}")

                    state["bet"] = bet
                    state["last_trade_time"] = time.time()

                    result = get_result(mid)
                    if not result:
                        continue

                    state["history"].append(result)

                    if result == state["side"]:
                        profit = bet * ((1 - trade_price) / trade_price)
                        bankroll += profit
                        state["profit"] += profit
                        print("✅ WIN", profit)

                        state["loss"] = 0
                        state["step"] = 1
                        state["active_trade"] = False
                    else:
                        bankroll -= bet
                        state["loss"] += bet
                        state["step"] += 1
                        print("❌ LOSS", bet)

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print("🔥 LOOP ERROR:", e)
            time.sleep(5)