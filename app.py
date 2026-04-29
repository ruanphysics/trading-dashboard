import requests
import time
import threading
from datetime import datetime, timezone
from flask import Flask, render_template_string

# =========================
# SETTINGS
# =========================
markets = ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD"]
stake_levels = [4, 8, 16]

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)

# =========================
# STATE
# =========================
state = {}
for m in markets:
    state[m] = {
        "up_streak": 0,
        "down_streak": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "entry_price": None,
        "entry_time": None,
        "current_bet": 0,
        "expected_profit": 0,
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

def get_countdown():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    remaining = 300 - (seconds % 300)
    return f"{remaining//60:02d}:{remaining%60:02d}"

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
            # WAIT for next candle FIRST
            wait = wait_for_next_candle()
            print(f"{m} waiting {wait}s")
            time.sleep(wait + 2)

            prev_close, last_close = get_last_two_closes(m)

            if prev_close is None:
                s["last_update"] = "No data"
                continue

            # Update heartbeat
            s["last_update"] = datetime.now().strftime("%H:%M:%S")

            # STREAK LOGIC
            if last_close > prev_close:
                s["up_streak"] += 1
                s["down_streak"] = 0
            else:
                s["down_streak"] += 1
                s["up_streak"] = 0

            print(f"{m} → U:{s['up_streak']} D:{s['down_streak']}")

            # ENTRY CONDITIONS
            if not s["in_trade"]:
                if s["up_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "DOWN"
                    s["step"] = 0
                    s["entry_time"] = datetime.now(timezone.utc)

                elif s["down_streak"] >= 3:
                    s["in_trade"] = True
                    s["trade_direction"] = "UP"
                    s["step"] = 0
                    s["entry_time"] = datetime.now(timezone.utc)

            # TRADING LOOP
            while s["in_trade"] and s["step"] < len(stake_levels):
                bet = stake_levels[s["step"]]

                s["current_bet"] = bet
                s["expected_profit"] = bet * 0.75
                s["entry_price"] = prev_close

                wait = wait_for_next_candle()
                time.sleep(wait + 2)

                prev_close, new_close = get_last_two_closes(m)

                win = False
                if s["trade_direction"] == "DOWN" and new_close < prev_close:
                    win = True
                elif s["trade_direction"] == "UP" and new_close > prev_close:
                    win = True

                if win:
                    profit = bet * 0.75
                    with bankroll_lock:
                        bankroll += profit

                    s["profit"] += profit

                    # RESET
                    s["in_trade"] = False
                    s["up_streak"] = 0
                    s["down_streak"] = 0
                    s["entry_price"] = None
                    s["entry_time"] = None
                    s["current_bet"] = 0
                    s["expected_profit"] = 0
                    break

                else:
                    with bankroll_lock:
                        bankroll -= bet

                    s["profit"] -= bet
                    s["step"] += 1

            # FAIL RESET
            if s["in_trade"] and s["step"] >= len(stake_levels):
                s["in_trade"] = False
                s["up_streak"] = 0
                s["down_streak"] = 0

        except Exception as e:
            print("THREAD ERROR:", e)

# =========================
# START BOTS (FIXED)
# =========================
def start_bots():
    print("STARTING ALL BOTS...")
    for m in markets:
        threading.Thread(target=run_market, args=(m,), daemon=True).start()

start_bots()

# =========================
# UI
# =========================
HTML = """
<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="3">
<style>
body { font-family: Arial; background:#0f172a; color:white; padding:20px;}
.card { background:#1e293b; padding:15px; margin:10px; border-radius:10px;}
.green { color:#22c55e;} .red {color:#ef4444;} .yellow {color:#facc15;}
</style>
</head>
<body>

<h1>📊 Trading Dashboard</h1>

<h2>💰 Bankroll: ${{bankroll}}</h2>
<h3>⏱ Next Candle: {{countdown}}</h3>

{% for m,s in state.items() %}
<div class="card">
<h2>{{m}}</h2>

<p>Streak: U{{s.up_streak}} / D{{s.down_streak}}</p>
<p>Last update: {{s.last_update}}</p>

{% if s.in_trade %}
<p class="yellow">Trading {{s.trade_direction}} Step {{s.step+1}}</p>
<p>Bet: ${{s.current_bet}}</p>
<p class="green">Profit: +${{s.expected_profit}}</p>
{% else %}
<p>Idle</p>
{% endif %}

<p>Market Profit:
{% if s.profit>=0 %}
<span class="green">{{s.profit}}</span>
{% else %}
<span class="red">{{s.profit}}</span>
{% endif %}
</p>

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
        bankroll=round(bankroll,2),
        countdown=get_countdown()
    )