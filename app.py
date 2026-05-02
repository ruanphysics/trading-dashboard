import time
import requests
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

ASSETS = ["btc", "eth", "sol", "xrp"]

ROUND_SECONDS = 300
SLEEP_TIME = 5

bankroll = 100.0
asset_states = {}
bot_started = False

app = Flask(__name__)

TEMPLATE = """
<meta http-equiv="refresh" content="5">

<h1>📊 DEBUG BOT</h1>

<p><b>Bankroll:</b> {{bankroll}}</p>

{% for a in assets %}
<div style="border:1px solid #ccc; padding:10px; margin:10px;">
<b>{{a['name']}}</b><br>

Market ID: {{a['market_id']}}<br>
Price: {{a['price']}}<br>
Tokens: {{a['tokens']}}<br>
Status: {{a['status']}}<br>

Time: {{a['time']}}<br>
Timer: {{a['timer']}}<br>

History: {{a['history']}}
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
    now, timer = get_timer()

    display = []
    for s in asset_states.values():
        display.append({
            "name": s["name"],
            "market_id": s["market_id"],
            "price": s.get("price"),
            "tokens": s.get("tokens"),
            "status": s.get("status"),
            "history": s.get("history"),
            "time": now,
            "timer": timer
        })

    return render_template_string(TEMPLATE, bankroll=bankroll, assets=display)

# =========================
# TIME
# =========================
def get_timer():
    now = datetime.utcnow()
    seconds = int(now.timestamp())
    remaining = 300 - (seconds % 300)

    return now.strftime("%H:%M:%S"), f"{remaining//60:02d}:{remaining%60:02d}"

def current_ts():
    now = int(time.time())
    return now - (now % ROUND_SECONDS)

# =========================
# API
# =========================
def safe_get_tokens(mid):
    try:
        url = f"https://gamma-api.polymarket.com/markets/{mid}"
        r = requests.get(url)

        if r.status_code != 200:
            return None

        data = r.json()

        tokens = {}
        for o in data.get("outcomes", []):
            name = o.get("name", "").lower()

            if "yes" in name:
                tokens["UP"] = o.get("token_id")
            elif "no" in name:
                tokens["DOWN"] = o.get("token_id")

        return tokens if tokens else None

    except:
        return None

def safe_get_price(token):
    try:
        r = requests.get(f"https://clob.polymarket.com/books/{token}")
        data = r.json()

        asks = data.get("asks", [])
        bids = data.get("bids", [])

        if asks:
            return float(asks[0]["price"])
        if bids:
            return float(bids[0]["price"])

    except:
        pass

    return None

def safe_get_result(mid):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{mid}").json()

        for o in data.get("outcomes", []):
            if o.get("winner"):
                return "UP" if "yes" in o["name"].lower() else "DOWN"

    except:
        pass

    return None

# =========================
# BOT LOOP
# =========================
def run_bot():
    global asset_states

    for a in ASSETS:
        asset_states[a] = {
            "name": a.upper(),
            "market_id": "",
            "price": None,
            "tokens": None,
            "status": "INIT",
            "history": []
        }

    while True:
        try:
            ts = current_ts()

            for a in ASSETS:
                s = asset_states[a]

                current_mid = f"{a}-updown-5m-{ts}"
                prev_mid = f"{a}-updown-5m-{ts - 300}"

                s["market_id"] = current_mid

                # TRY CURRENT + PREVIOUS (important fix)
                tokens = safe_get_tokens(current_mid)

                if not tokens:
                    tokens = safe_get_tokens(prev_mid)

                s["tokens"] = tokens

                if not tokens:
                    s["status"] = "NO TOKENS"
                    continue

                price = safe_get_price(tokens.get("UP"))
                s["price"] = price

                if not price:
                    s["status"] = "NO PRICE"
                    continue

                s["status"] = "LIVE"

                # CHECK RESULT (previous round)
                result = safe_get_result(prev_mid)

                if result and (not s["history"] or s["history"][-1] != result):
                    s["history"].append(result)

                    if len(s["history"]) > 10:
                        s["history"].pop(0)

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(5)

# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))