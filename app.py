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
<meta http-equiv="refresh" content="5">

<h1>📊 Polymarket 5m Bot (FINAL FIX)</h1>

<p><b>Bankroll:</b> {{bankroll}}</p>

{% for a in assets %}
<div style="border:1px solid #ccc; padding:10px; margin:10px;">
<b>{{a['name']}}</b><br>

Market ID: {{a['market_id']}}<br>
Slug: {{a['slug']}}<br>
Price: {{a['price']}}<br>
Status: {{a['status']}}<br>

<br>
⏱ Time (UTC): {{a['time']}}<br>

<br>
History: {{a['history']}}
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
    now = datetime.utcnow().strftime("%H:%M:%S")

    display = []
    for s in asset_states.values():
        display.append({
            "name": s["name"],
            "market_id": s.get("market_id"),
            "slug": s.get("slug"),
            "price": s.get("price"),
            "status": s.get("status"),
            "history": s.get("history"),
            "time": now
        })

    return render_template_string(TEMPLATE, bankroll=bankroll, assets=display)

# =========================
# 🔥 FIXED MARKET FETCH (PAGINATION)
# =========================
def get_live_markets():
    try:
        found = {}

        offset = 0

        while offset < 2000:  # scan up to 2000 markets
            data = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "limit": 200,
                    "offset": offset,
                    "active": "true"
                }
            ).json()

            if not data:
                break

            for m in data:
                slug = m.get("slug", "").lower()

                for asset in ASSETS:
                    if f"{asset}-updown-5m" in slug:
                        found[asset] = m

            # stop early if all found
            if len(found) == len(ASSETS):
                return found

            offset += 200

        return found

    except Exception as e:
        print("MARKET ERROR:", e)
        return {}

# =========================
# PRICE
# =========================
def get_price(token):
    try:
        data = requests.get(f"https://clob.polymarket.com/books/{token}").json()

        asks = data.get("asks", [])
        bids = data.get("bids", [])

        if asks and bids:
            return (float(asks[0]["price"]) + float(bids[0]["price"])) / 2

        if asks:
            return float(asks[0]["price"])

        if bids:
            return float(bids[0]["price"])

    except:
        pass

    return None

# =========================
# RESULT
# =========================
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
# BOT LOOP
# =========================
def run_bot():
    global asset_states

    for a in ASSETS:
        asset_states[a] = {
            "name": a.upper(),
            "market_id": None,
            "slug": None,
            "price": None,
            "status": "INIT",
            "history": [],
            "last_result": None
        }

    while True:
        try:
            markets = get_live_markets()

            print("Markets found:", list(markets.keys()))

            for a in ASSETS:
                s = asset_states[a]

                m = markets.get(a)

                if not m:
                    s["status"] = "NOT FOUND"
                    continue

                mid = m.get("id")
                slug = m.get("slug")

                s["market_id"] = mid
                s["slug"] = slug

                # TOKENS
                tokens = {}
                for o in m.get("outcomes", []):
                    name = o["name"].lower()

                    if "yes" in name:
                        tokens["UP"] = o["token_id"]
                    elif "no" in name:
                        tokens["DOWN"] = o["token_id"]

                if "UP" not in tokens:
                    s["status"] = "NO TOKENS"
                    continue

                price = get_price(tokens["UP"])
                s["price"] = price

                s["status"] = "LIVE" if price else "NO PRICE"

                # RESULT
                result = get_result(mid)

                if result and result != s["last_result"]:
                    s["last_result"] = result
                    s["history"].append(result)

                    if len(s["history"]) > 10:
                        s["history"].pop(0)

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print("🔥 LOOP ERROR:", e)
            time.sleep(5)

# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))