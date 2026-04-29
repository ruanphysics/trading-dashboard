import requests
import time
import threading
from datetime import datetime, timezone
from flask import Flask, render_template_string

markets = ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD"]
stake_levels = [4, 8, 16]

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

state = {}
for m in markets:
    state[m] = {
        "up_streak": 0,
        "down_streak": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "last_update": "starting..."
    }

# =========================
# TIME
# =========================
def wait_for_next_candle():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    wait = 300 - (seconds % 300)
    return wait

# =========================
# DATA
# =========================
def get_last_two_closes(market):
    try:
        url = f"https://api.exchange.coinbase.com/products/{market}/candles?granularity=300"
        data = requests.get(url, timeout=10).json()

        if len(data) < 2:
            return None, None

        return data[1][4], data[0][4]

    except Exception as e:
        print("API ERROR:", e)
        return None, None

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    print(f"STARTED BOT: {m}")

    while True:
        try:
            wait = wait_for_next_candle()
            print(f"{m} waiting {wait}s")
            time.sleep(wait + 2)

            prev_close, last_close = get_last_two_closes(m)

            if prev_close is None:
                s["last_update"] = "No data"
                continue

            # DEBUG TRACK
            s["last_update"] = datetime.now().strftime("%H:%M:%S")

            if last_close > prev_close:
                s["up_streak"] += 1
                s["down_streak"] = 0
            else:
                s["down_streak"] += 1
                s["up_streak"] = 0

            print(f"{m} → U:{s['up_streak']} D:{s['down_streak']}")

        except Exception as e:
            print("THREAD ERROR:", e)

# =========================
# START THREADS (IMPORTANT FIX)
# =========================
@app.before_first_request
def start_bots():
    print("STARTING ALL BOTS...")
    for m in markets:
        threading.Thread(target=run_market, args=(m,), daemon=True).start()

# =========================
# UI
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="3"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h1>Dashboard</h1>
<h2>Bank: ${{bankroll}}</h2>

{% for m,s in state.items() %}
<div style="margin:10px;padding:10px;background:#1e293b">
<h3>{{m}}</h3>
<p>U:{{s.up_streak}} D:{{s.down_streak}}</p>
<p>Last update: {{s.last_update}}</p>
</div>
{% endfor %}

</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, state=state, bankroll=bankroll)