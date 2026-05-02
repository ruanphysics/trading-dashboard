import time
import requests
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

# =========================
# CONFIG
# =========================
ASSETS = ["btc", "eth", "sol", "xrp"]

BASE_BET = 1.0
TARGET_PROFIT = 0.30
MAX_BET = 5.0
MAX_STEPS = 10

ROUND_SECONDS = 300
SLEEP_TIME = 5

# =========================
# STATE
# =========================
bankroll = 100.0
asset_states = {}
bot_started = False

# =========================
# FLASK
# =========================
app = Flask(__name__)

TEMPLATE = """
<h1>📊 5-Min Strategy (Stable)</h1>

<p><b>Bankroll:</b> {{bankroll}}</p>

{% for a in assets %}
<div style="border:1px solid #ccc; padding:10px; margin:10px;">
<b>{{a['name']}}</b><br>

Market ID: {{a['market_id']}}<br>
Price: {{a['price']}}<br>
Status: {{a['status']}}<br>
Bet: {{a['bet']}}<br>
Profit: {{a['profit']}}<br>
Step: {{a['step']}}<br>
Loss: {{a['loss']}}<br>

<br>
<b>⏱ Time (UTC)</b><br>
Now: {{a['time']}}<br>
Ends In: {{a['timer']}}<br>

<br>
<b>History:</b> {{a['history']}}<br>
<b>Prices:</b> {{a['prices']}}
</div>
{% endfor %}
"""

@app.before_request
def start_bot():
    global bot_started
    if not bot_started:
        threading.Thread(target=run_bot, daemon=True).start()
        bot_started = True

@app.route("/")
def home():
    display = []

    now, timer = get_timer()

    for s in asset_states.values():
        display.append({
            "name": s["name"],
            "market_id": s["market_id"],
            "price": round(s.get("price", 0), 3),
            "status": "Waiting for pattern" if not s["active"] else f"Betting {s['side']}",
            "bet": round(s.get("bet", 0), 2),
            "profit": round(s.get("profit", 0), 2),
            "step": s["step"],
            "loss": round(s["loss"], 2),
            "history": s["history"],
            "prices": [round(p, 3) for p in s["prices"]],
            "time": now,
            "timer": timer
        })

    return render_template_string(TEMPLATE, bankroll=round(bankroll, 2), assets=display)

# =========================
# TIME (FIXED)
# =========================
def get_timer():
    now = datetime.utcnow()
    seconds = int(now.timestamp())
    remaining = 300 - (seconds % 300)

    mins = remaining // 60
    secs = remaining % 60

    return now.strftime("%H:%M:%S"), f"{mins:02d}:{secs:02d}"

def current_timestamp():
    now = int(time.time())
    return now - (now % ROUND_SECONDS)

# =========================
# API HELPERS
# =========================
def get_tokens(mid):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{mid}").json()

        tokens = {}
        for o in data.get("outcomes", []):
            name = o.get("name", "").lower()

            if name in ["yes", "up"]:
                tokens["UP"] = o.get("token_id")
            elif name in ["no", "down"]:
                tokens["DOWN"] = o.get("token_id")

        return tokens
    except:
        return {}

# 🔥 FIXED PRICE FUNCTION
def get_price(token):
    try:
        data = requests.get(f"https://clob.polymarket.com/books/{token}").json()

        asks = data.get("asks", [])
        bids = data.get("bids", [])

        best_ask = float(asks[0]["price"]) if asks else None
        best_bid = float(bids[0]["price"]) if bids else None

        if best_ask and best_bid:
            return (best_ask + best_bid) / 2

        return best_ask or best_bid

    except:
        return None

def get_result(mid):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{mid}").json()
        for o in data.get("outcomes", []):
            if o.get("winner"):
                return "UP" if "yes" in o["name"].lower() else "DOWN"
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

def calc_bet(price, s):
    if not price or price <= 0 or price >= 1:
        return BASE_BET

    required = s["loss"] + TARGET_PROFIT
    raw = required * (price / (1 - price))

    return max(min(raw, MAX_BET), BASE_BET)

# =========================
# BOT LOOP (FIXED)
# =========================
def run_bot():
    global bankroll

    for a in ASSETS:
        asset_states[a] = {
            "name": a.upper(),
            "market_id": "",
            "prices": [],
            "history": [],
            "loss": 0,
            "step": 1,
            "active": False,
            "side": None,
            "bet": 0,
            "profit": 0,
            "last_trade": None,
            "last_resolved": None
        }

    while True:
        try:
            ts = current_timestamp()

            for a in ASSETS:
                s = asset_states[a]

                current_mid = f"{a}-updown-5m-{ts}"
                prev_mid = f"{a}-updown-5m-{ts - 300}"

                s["market_id"] = current_mid

                tokens = get_tokens(current_mid)
                if "UP" not in tokens or "DOWN" not in tokens:
                    continue

                price = get_price(tokens["UP"])
                if not price:
                    continue

                s["price"] = price
                s["prices"].append(price)

                if len(s["prices"]) > 6:
                    s["prices"].pop(0)

                # DETECT SIGNAL
                if not s["active"]:
                    signal = detect_streak(s["prices"])
                    if signal:
                        s["active"] = True
                        s["side"] = signal
                        print(f"🔥 {a.upper()} SIGNAL {signal}")

                # TRADE ONCE PER ROUND
                if s["active"] and s["last_trade"] != ts:
                    trade_price = get_price(tokens[s["side"]])
                    if not trade_price:
                        continue

                    bet = calc_bet(trade_price, s)
                    s["bet"] = bet
                    s["last_trade"] = ts

                    print(f"🧪 {a.upper()} BET {s['side']} ${bet:.2f}")

                # CHECK RESULT OF PREVIOUS ROUND
                result = get_result(prev_mid)

                if result and s["last_resolved"] != prev_mid:
                    s["last_resolved"] = prev_mid
                    s["history"].append(result)

                    if len(s["history"]) > 12:
                        s["history"].pop(0)

                    if s["active"]:
                        if result == s["side"]:
                            profit = s["bet"] * ((1 - price) / price)
                            bankroll += profit
                            s["profit"] += profit

                            s["loss"] = 0
                            s["step"] = 1
                            s["active"] = False

                            print(f"✅ {a.upper()} WIN {profit:.2f}")

                        else:
                            bankroll -= s["bet"]
                            s["loss"] += s["bet"]
                            s["step"] += 1

                            print(f"❌ {a.upper()} LOSS {s['bet']:.2f}")

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