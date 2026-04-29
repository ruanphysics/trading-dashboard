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
        "last_close": None,
        "up_streak": 0,
        "down_streak": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "entry_price": None,
        "entry_time": None,
        "current_bet": 0,
        "expected_profit": 0
    }

# =========================
# TIME
# =========================
def wait_for_next_candle():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    wait = 300 - (seconds % 300)
    time.sleep(wait)

def get_countdown():
    now = datetime.now(timezone.utc)
    seconds = now.minute * 60 + now.second
    remaining = 300 - (seconds % 300)

    mins = remaining // 60
    secs = remaining % 60

    return f"{mins:02d}:{secs:02d}"

# =========================
# DATA
# =========================
def get_last_two_closes(market):
    url = f"https://api.exchange.coinbase.com/products/{market}/candles?granularity=300"
    data = requests.get(url).json()

    if len(data) < 2:
        return None, None

    latest = data[0][4]
    previous = data[1][4]

    return previous, latest

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]

    while True:
        try:
            prev_close, last_close = get_last_two_closes(m)

            if prev_close is None:
                time.sleep(5)
                continue

            if last_close > prev_close:
                s["up_streak"] += 1
                s["down_streak"] = 0
            else:
                s["down_streak"] += 1
                s["up_streak"] = 0

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

            while s["in_trade"] and s["step"] < len(stake_levels):
                bet = stake_levels[s["step"]]

                s["current_bet"] = bet
                s["expected_profit"] = bet * 0.75
                s["entry_price"] = prev_close

                wait_for_next_candle()

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

                    # reset
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

            if s["in_trade"] and s["step"] >= len(stake_levels):
                s["in_trade"] = False
                s["up_streak"] = 0
                s["down_streak"] = 0
                s["entry_price"] = None
                s["entry_time"] = None
                s["current_bet"] = 0
                s["expected_profit"] = 0

        except:
            pass

        wait_for_next_candle()

# =========================
# START THREADS
# =========================
def start_bots():
    for m in markets:
        t = threading.Thread(target=run_market, args=(m,), daemon=True)
        t.start()

# =========================
# WEB UI
# =========================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Trading Dashboard</title>
    <meta http-equiv="refresh" content="2">
    <style>
        body { font-family: Arial; background: #0f172a; color: white; padding: 20px; }
        h1 { color: #38bdf8; }
        .bank { font-size: 26px; margin-bottom: 10px; }
        .countdown { font-size: 18px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
        .card { background: #1e293b; padding: 15px; border-radius: 12px; }
        .green { color: #22c55e; }
        .red { color: #ef4444; }
        .yellow { color: #facc15; }
        .idle { color: #94a3b8; }
    </style>
</head>
<body>

<h1>📊 Trading Dashboard</h1>

<div class="bank">💰 Bankroll: ${{ bankroll }}</div>
<div class="countdown">⏱ Next candle: <b>{{ countdown }}</b></div>

<div class="grid">
{% for m, s in state.items() %}
<div class="card">
<h2>{{ m }}</h2>

<p><b>Streak:</b> U:{{ s.up_streak }} | D:{{ s.down_streak }}</p>

<p>
<b>Status:</b><br>
{% if s.in_trade %}
<span class="yellow">TRADING {{ s.trade_direction }} (Step {{ s.step+1 }})</span><br>
Bet: ${{ s.current_bet }}<br>
Expected Profit: <span class="green">+${{ "%.2f"|format(s.expected_profit) }}</span><br>
Return: ${{ "%.2f"|format(s.current_bet + s.expected_profit) }}<br>
Entry: {{ s.entry_price }}<br>
Time: {{ s.entry_time }}
{% else %}
<span class="idle">IDLE</span>
{% endif %}
</p>

<p>
<b>Profit:</b>
{% if s.profit >= 0 %}
<span class="green">{{ "%.2f"|format(s.profit) }}</span>
{% else %}
<span class="red">{{ "%.2f"|format(s.profit) }}</span>
{% endif %}
</p>

</div>
{% endfor %}
</div>

</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(
        HTML,
        state=state,
        bankroll=round(bankroll, 2),
        countdown=get_countdown()
    )

# =========================
# INIT (IMPORTANT FOR RENDER)
# =========================
start_bots()