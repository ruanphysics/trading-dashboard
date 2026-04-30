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
stake_levels = [4, 8, 16]
STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

# =========================
# FETCH MARKETS
# =========================
def fetch_markets():
    try:
        url = "https://gamma-api.polymarket.com/markets"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except:
        pass
    return None

# =========================
# FIND BEST MARKET (LOCKING)
# =========================
def find_best_market(asset):
    data = fetch_markets()
    if not data:
        return None

    asset_map = {
        "bitcoin": ["bitcoin", "btc"],
        "ethereum": ["ethereum", "eth"],
        "ripple": ["ripple", "xrp"],
        "solana": ["solana", "sol"]
    }

    keywords = asset_map.get(asset, [asset])

    best_market = None
    best_time_diff = float("inf")
    now = datetime.now(timezone.utc)

    for m in data:
        try:
            title = m.get("question", "").lower()

            if not any(k in title for k in keywords):
                continue

            if not m.get("active", True):
                continue

            end_time = m.get("endDate")
            if not end_time:
                continue

            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            diff = (end - now).total_seconds()

            if diff <= 0:
                continue

            if diff < best_time_diff:
                best_time_diff = diff
                best_market = m

        except:
            continue

    return best_market

# =========================
# GET MARKET INFO
# =========================
def get_market_info(asset, locked_market):
    # use locked market if valid
    if locked_market:
        try:
            outcomes = locked_market.get("outcomes", [])
            price = float(outcomes[0]["price"])
            end_time = locked_market.get("endDate")

            if 0 < price < 1:
                return price, end_time, locked_market
        except:
            pass

    # otherwise find new one
    new_market = find_best_market(asset)
    if not new_market:
        return None, None, None

    try:
        price = float(new_market["outcomes"][0]["price"])
        end_time = new_market.get("endDate")
        return price, end_time, new_market
    except:
        return None, None, None

# =========================
# SAFE FETCH
# =========================
def safe_get_info(asset, last_price, locked_market):
    for _ in range(3):
        price, end_time, market = get_market_info(asset, locked_market)
        if price is not None:
            return price, end_time, market
        time.sleep(2)

    return last_price, None, locked_market

# =========================
# COUNTDOWN
# =========================
def get_time_remaining(end_time):
    try:
        if not end_time:
            return "--:--"

        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        diff = (end - now).total_seconds()

        if diff <= 0:
            return "00:00"

        mins = int(diff // 60)
        secs = int(diff % 60)

        return f"{mins:02d}:{secs:02d}"
    except:
        return "--:--"

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
        "up_streak": 0,
        "down_streak": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "entry_price": None,
        "current_bet": 0,
        "expected_profit": 0,
        "last_price": None,
        "last_update": "Starting...",
        "countdown": "--:--",
        "market": None
    }

loaded = load_state()
state = loaded if loaded else default_state

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    print(f"STARTED BOT: {m}")

    while True:
        try:
            time.sleep(60)

            price, end_time, market = safe_get_info(m, s["last_price"], s["market"])
            s["market"] = market

            if price is None:
                s["last_update"] = "No data"
                continue

            s["countdown"] = get_time_remaining(end_time)

            if s["last_price"] is None:
                s["last_price"] = price
                continue

            s["last_update"] = datetime.now().strftime("%H:%M:%S")

            # STREAK LOGIC (UNCHANGED)
            if price > s["last_price"]:
                s["up_streak"] += 1
                s["down_streak"] = 0
            elif price < s["last_price"]:
                s["down_streak"] += 1
                s["up_streak"] = 0

            s["last_price"] = price

            # ENTRY (UNCHANGED)
            if not s["in_trade"]:
                if s["up_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "DOWN"
                    s["step"] = 0

                elif s["down_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "UP"
                    s["step"] = 0

            # TRADE LOOP (UNCHANGED)
            while s["in_trade"] and s["step"] < len(stake_levels):
                bet = stake_levels[s["step"]]
                entry_price = s["last_price"]

                s["current_bet"] = bet
                s["entry_price"] = entry_price
                s["expected_profit"] = round(bet * (1 - entry_price), 2)

                time.sleep(300)

                new_price, _, _ = safe_get_info(m, entry_price, s["market"])

                if new_price is None:
                    continue

                win = False
                if s["trade_direction"] == "DOWN" and new_price < entry_price:
                    win = True
                elif s["trade_direction"] == "UP" and new_price > entry_price:
                    win = True

                if win:
                    profit = bet * (1 - entry_price)
                    with bankroll_lock:
                        bankroll += profit

                    s["profit"] += profit
                    s["in_trade"] = False
                    s["up_streak"] = 0
                    s["down_streak"] = 0
                    break

                else:
                    loss = bet * entry_price
                    with bankroll_lock:
                        bankroll -= loss

                    s["profit"] -= loss
                    s["step"] += 1

            if s["in_trade"] and s["step"] >= len(stake_levels):
                s["in_trade"] = False
                s["up_streak"] = 0
                s["down_streak"] = 0

            save_state()

        except Exception as e:
            print("THREAD ERROR:", e)

# =========================
# START BOTS
# =========================
bots_started = False

@app.before_request
def start_once():
    global bots_started
    if not bots_started:
        print("🔥 STARTING BOTS...")
        for m in markets:
            threading.Thread(target=run_market, args=(m,), daemon=True).start()
        bots_started = True

# =========================
# UI
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Polymarket Bot</h1>
<h2>Bank: ${{bankroll}}</h2>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>

<p>⏳ {{s.countdown}}</p>
<p>U:{{s.up_streak}} D:{{s.down_streak}}</p>
<p>Last price: {{s.last_price}}</p>
<p>Last update: {{s.last_update}}</p>

{% if s.in_trade %}
<p>Trading {{s.trade_direction}} (step {{s.step+1}})</p>
<p>Bet: ${{s.current_bet}}</p>
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
    return render_template_string(
        HTML,
        state=state,
        bankroll=round(bankroll, 2)
    )

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)