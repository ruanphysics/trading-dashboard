import requests
import time
import threading
import json
import os
from datetime import datetime
import pytz
from flask import Flask, jsonify, render_template_string

# =========================
# SETTINGS
# =========================
markets = ["bitcoin", "ethereum", "ripple", "solana"]

slug_map = {
    "bitcoin": "btc-updown-5m",
    "ethereum": "eth-updown-5m",
    "ripple": "xrp-updown-5m",
    "solana": "sol-updown-5m"
}

symbols = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "ripple": "XRP-USD",
    "solana": "SOL-USD"
}

stake_levels = [4, 8, 16]
STATE_FILE = "state.json"

bankroll = 100
bankroll_lock = threading.Lock()

app = Flask(__name__)
ET = pytz.timezone("America/New_York")
START_TIME = time.time()

# =========================
# TIME
# =========================
def get_et_timestamp():
    return int(datetime.now(ET).timestamp())

def get_round_times():
    now = get_et_timestamp()
    end = now - (now % 300)
    start = end - 300
    return start, end

def get_countdown_seconds():
    return 300 - (get_et_timestamp() % 300)

def get_uptime():
    s = int(time.time() - START_TIME)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

# =========================
# COINBASE PRICE
# =========================
def get_coinbase_price(symbol):
    try:
        r = requests.get(f"https://api.exchange.coinbase.com/products/{symbol}/ticker", timeout=5).json()
        return float(r["price"])
    except:
        return None

# =========================
# 🔥 AUTO TOKEN ID EXTRACTOR
# =========================
def get_token_ids(market):
    try:
        slug = slug_map[market]

        res = requests.get("https://gamma-api.polymarket.com/events", timeout=5)
        if res.status_code != 200:
            return None, None

        data = res.json()

        # filter matching slug
        matches = [e for e in data if slug in e.get("slug", "")]

        if not matches:
            return None, None

        # get latest timestamp
        latest = max(matches, key=lambda x: int(x["slug"].split("-")[-1]))

        markets_data = latest.get("markets", [])
        if not markets_data:
            return None, None

        outcomes = markets_data[0].get("outcomes", [])

        if len(outcomes) < 2:
            return None, None

        yes_token = outcomes[0].get("token_id")
        no_token = outcomes[1].get("token_id")

        return yes_token, no_token

    except:
        return None, None

# =========================
# CLOB
# =========================
def get_clob_data(token_id):
    if not token_id:
        return None
    try:
        r = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=5).json()

        bids = r.get("bids", [])
        asks = r.get("asks", [])

        bid_liq = sum(float(b[1]) for b in bids[:5])
        ask_liq = sum(float(a[1]) for a in asks[:5])

        best_bid = float(bids[0][0]) if bids else 0

        return bid_liq, ask_liq, best_bid
    except:
        return None

def get_clob_sentiment(market):
    yes_id, no_id = get_token_ids(market)

    yes = get_clob_data(yes_id)
    no = get_clob_data(no_id)

    if not yes or not no:
        return None, 0, 0, 0

    up_liq = yes[0]
    down_liq = no[0]
    best_bid = yes[2]

    if up_liq > down_liq * 1.2:
        signal = "UP"
    elif down_liq > up_liq * 1.2:
        signal = "DOWN"
    else:
        signal = None

    return signal, round(up_liq,2), round(down_liq,2), best_bid

# =========================
# STATE
# =========================
default_state = {
    m: {
        "history": [],
        "start_price": None,
        "current_price": None,
        "signal": None,
        "clob_signal": None,
        "up_liq": 0,
        "down_liq": 0,
        "best_bid": 0,
        "in_trade": False,
        "trade_direction": None,
        "step": 0,
        "profit": 0,
        "round": "",
        "countdown": 0,
        "last_update": "Starting..."
    } for m in markets
}

state = default_state

# =========================
# BOT
# =========================
def run_market(m):
    global bankroll
    s = state[m]
    last_round = None

    while True:
        time.sleep(3)

        start, end = get_round_times()
        s["countdown"] = get_countdown_seconds()
        s["round"] = datetime.fromtimestamp(end, ET).strftime("%H:%M")

        price = get_coinbase_price(symbols[m])
        if not price:
            continue

        s["current_price"] = price

        # 🔥 CLOB UPDATE
        clob_signal, up_liq, down_liq, best_bid = get_clob_sentiment(m)
        s["clob_signal"] = clob_signal
        s["up_liq"] = up_liq
        s["down_liq"] = down_liq
        s["best_bid"] = best_bid

        if last_round is None:
            last_round = end
            s["start_price"] = price
            continue

        if end != last_round:
            outcome = "UP" if price > s["start_price"] else "DOWN"

            s["history"].append(outcome)
            if len(s["history"]) > 7:
                s["history"].pop(0)

            # PATTERN
            if len(s["history"]) >= 3:
                last3 = s["history"][-3:]
                if last3 == ["UP","UP","UP"]:
                    s["signal"] = "DOWN"
                elif last3 == ["DOWN","DOWN","DOWN"]:
                    s["signal"] = "UP"
                else:
                    s["signal"] = None

            # ENTRY
            if s["signal"] and not s["in_trade"]:
                if s["signal"] == s["clob_signal"]:
                    s["in_trade"] = True
                    s["trade_direction"] = s["signal"]
                    s["step"] = 0

            # EXECUTION
            if s["in_trade"]:
                bet = stake_levels[s["step"]]
                win = (
                    (s["trade_direction"]=="UP" and outcome=="UP") or
                    (s["trade_direction"]=="DOWN" and outcome=="DOWN")
                )

                if win:
                    bankroll += bet
                    s["profit"] += bet
                    s["in_trade"] = False
                    s["signal"] = None
                else:
                    bankroll -= bet
                    s["profit"] -= bet
                    s["step"] += 1
                    if s["step"] >= len(stake_levels):
                        s["in_trade"] = False
                        s["signal"] = None

            s["start_price"] = price
            last_round = end

        s["last_update"] = datetime.now(ET).strftime("%H:%M:%S")

# =========================
# START THREADS
# =========================
started=False
@app.before_request
def start():
    global started
    if not started:
        for m in markets:
            threading.Thread(target=run_market,args=(m,),daemon=True).start()
        started=True

# =========================
# API
# =========================
@app.route("/data")
def data():
    return jsonify({"state":state,"bankroll":bankroll,"uptime":get_uptime()})

# =========================
# UI
# =========================
HTML = """
<html>
<script>
async function load(){
 let r=await fetch('/data'); let d=await r.json();
 document.getElementById("bank").innerText=d.bankroll;
 document.getElementById("up").innerText=d.uptime;

 for (const [m,s] of Object.entries(d.state)){
  document.getElementById(m+"_sig").innerText=s.signal||"-";
  document.getElementById(m+"_clob").innerText=s.clob_signal||"-";
  document.getElementById(m+"_liq").innerText="UP:"+s.up_liq+" DOWN:"+s.down_liq;
  document.getElementById(m+"_price").innerText=s.current_price||"-";
  document.getElementById(m+"_hist").innerText=s.history.join(",");
 }
}
setInterval(load,3000);
</script>

<body style="background:#111;color:white">
<h2>Bank: $<span id="bank"></span></h2>
<div>Uptime: <span id="up"></span></div>

{% for m in state %}
<div style="border:1px solid #444;margin:10px;padding:10px">
<h3>{{m}}</h3>
<p>Pattern: <span id="{{m}}_sig"></span></p>
<p>CLOB: <span id="{{m}}_clob"></span></p>
<p>Liquidity: <span id="{{m}}_liq"></span></p>
<p>Price: <span id="{{m}}_price"></span></p>
<p>History: <span id="{{m}}_hist"></span></p>
</div>
{% endfor %}
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML,state=state)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)