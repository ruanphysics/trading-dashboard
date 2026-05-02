import time
import requests
import os
import threading
from flask import Flask, render_template_string

# =========================
# CONFIG
# =========================
ROUND = 300
SLEEP = 2

BASE_BET = 1.0
TARGET_PROFIT = 0.30
MAX_BET = 5.0
MAX_STEPS = 10

MIN_UP_PRICE = 0.45
MAX_DOWN_PRICE = 0.55
ENTRY_WINDOW = 60

# =========================
# 🔥 PASTE YOUR LINKS HERE
# =========================
MARKETS = {
    "BTC": "https://polymarket.com/event/btc-updown-5m-1777748400",
    "ETH": "https://polymarket.com/event/eth-updown-5m-1777748400",
    "SOL": "https://polymarket.com/event/sol-updown-5m-1777748400",
    "XRP": "https://polymarket.com/event/xrp-updown-5m-1777748400",
}

# =========================
bankroll = 100.0
states = {}

app = Flask(__name__)

# =========================
# UI
# =========================
TEMPLATE = """
<meta http-equiv="refresh" content="3">
<h2>📊 FINAL BOT (AUTO TOKENS)</h2>
<h3>Bankroll: {{bankroll}}</h3>

{% for s in data %}
<div style="border:1px solid #aaa; padding:10px; margin:10px;">
<b>{{s.name}}</b><br>

Price: {{s.price}}<br>
Direction: {{s.side}}<br>
Entry: {{s.entry}}<br>
Bet: {{s.bet}}<br>

Step: {{s.step}} | Loss: {{s.loss}}<br>
Status: {{s.status}}<br>

⏱ {{s.timer}}<br>
History: {{s.history}}
</div>
{% endfor %}
"""

@app.route("/")
def home():
    return render_template_string(TEMPLATE, bankroll=bankroll, data=states.values())

# =========================
# HELPERS
# =========================
def get_slug(url):
    return url.split("/")[-1]

def get_tokens_from_slug(slug):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/events/{slug}").json()

        for m in data.get("markets", []):
            tokens = {}
            for o in m.get("outcomes", []):
                name = o["name"].lower()
                if "yes" in name:
                    tokens["UP"] = o["token_id"]
                elif "no" in name:
                    tokens["DOWN"] = o["token_id"]

            if "UP" in tokens and "DOWN" in tokens:
                return tokens
    except:
        pass

    return None

def get_price(token):
    try:
        d = requests.get(f"https://clob.polymarket.com/books/{token}").json()
        asks = d.get("asks", [])
        bids = d.get("bids", [])

        if asks and bids:
            return (float(asks[0]["price"]) + float(bids[0]["price"])) / 2
        if asks:
            return float(asks[0]["price"])
        if bids:
            return float(bids[0]["price"])
    except:
        pass
    return None

def timer():
    now = int(time.time())
    return ROUND - (now % ROUND)

def detect(hist):
    if len(hist) < 4:
        return None
    last = hist[-3:]
    if all(x == "DOWN" for x in last):
        return "UP"
    if all(x == "UP" for x in last):
        return "DOWN"
    return None

def calc(price, loss):
    required = loss + TARGET_PROFIT
    raw = required * (price / (1 - price))
    return min(max(raw, BASE_BET), MAX_BET)

# =========================
# BOT LOOP
# =========================
def run():
    global bankroll

    for name in MARKETS:
        states[name] = {
            "name": name,
            "price": None,
            "history": [],
            "side": None,
            "entry": None,
            "bet": 0,
            "step": 1,
            "loss": 0,
            "active": False,
            "status": "INIT",
            "start_price": None,
            "tokens": None
        }

    last_round = None

    while True:
        try:
            t = timer()

            for name, url in MARKETS.items():
                s = states[name]

                slug = get_slug(url)

                # refresh tokens every new round
                if not s["tokens"] or t > 290:
                    s["tokens"] = get_tokens_from_slug(slug)

                if not s["tokens"]:
                    s["status"] = "NO TOKENS"
                    continue

                price = get_price(s["tokens"]["UP"])
                s["price"] = round(price, 3) if price else None

                current_round = int(time.time() // ROUND)

                if last_round != current_round:
                    # resolve
                    if s["active"] and s["entry"]:
                        final = price

                        if final:
                            win = (
                                (s["side"] == "UP" and final > s["entry"]) or
                                (s["side"] == "DOWN" and final < s["entry"])
                            )

                            if win:
                                profit = s["bet"] * ((1 - s["entry"]) / s["entry"])
                                bankroll += profit
                                s["loss"] = 0
                                s["step"] = 1
                                s["status"] = "WIN ✅"
                            else:
                                bankroll -= s["bet"]
                                s["loss"] += s["bet"]
                                s["step"] += 1
                                s["status"] = "LOSS ❌"

                                if s["step"] > MAX_STEPS:
                                    s["loss"] = 0
                                    s["step"] = 1
                                    s["status"] = "RESET ⚠️"

                    # update history
                    if s["start_price"] and price:
                        s["history"].append("UP" if price > s["start_price"] else "DOWN")
                        if len(s["history"]) > 10:
                            s["history"].pop(0)

                    s["start_price"] = price
                    s["active"] = False
                    s["entry"] = None

                # ENTRY LOGIC
                if not s["active"] and price and t <= ENTRY_WINDOW:
                    sig = detect(s["history"])

                    if sig == "UP" and price <= MIN_UP_PRICE:
                        b = calc(price, s["loss"])
                        s["side"] = "UP"
                        s["entry"] = price
                        s["bet"] = round(b, 2)
                        s["active"] = True
                        s["status"] = "ENTER UP 🔵"

                    elif sig == "DOWN" and price >= MAX_DOWN_PRICE:
                        b = calc(price, s["loss"])
                        s["side"] = "DOWN"
                        s["entry"] = price
                        s["bet"] = round(b, 2)
                        s["active"] = True
                        s["status"] = "ENTER DOWN 🔴"

                    else:
                        s["status"] = "WAITING PRICE"

                elif not s["active"]:
                    s["status"] = "WAITING PATTERN"

                s["timer"] = f"{t//60:02d}:{t%60:02d}"

            last_round = int(time.time() // ROUND)
            time.sleep(SLEEP)

        except Exception as e:
            print("ERR:", e)
            time.sleep(2)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))