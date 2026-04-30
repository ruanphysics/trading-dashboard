import requests
import time
import threading
from datetime import datetime
import pytz
from flask import Flask, jsonify, render_template_string

# =========================
# SETTINGS
# =========================
markets = ["bitcoin", "ethereum", "ripple", "solana"]

symbols = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "ripple": "XRP-USD",
    "solana": "SOL-USD"
}

# 🔥 STABLE TOKEN IDS (EXAMPLE — replace if needed later)
TOKEN_IDS = {
    "bitcoin": {
        "yes": "0x6b8e6b5d2b6a6b1c9c9fbb6b7e4cbbf8c0f3c5d8",
        "no":  "0x1c2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e"
    },
    "ethereum": {
        "yes": "0xa1b2c3d4e5f67890123456789abcdefabcdef1234",
        "no":  "0xb1c2d3e4f567890123456789abcdefabcdef5678"
    },
    "ripple": {
        "yes": "0xc1d2e3f4567890123456789abcdefabcdef9012",
        "no":  "0xd1e2f3a4567890123456789abcdefabcdef3456"
    },
    "solana": {
        "yes": "0xe1f2a3b4567890123456789abcdefabcdef7890",
        "no":  "0xf1a2b3c4567890123456789abcdefabcdef1122"
    }
}

app = Flask(__name__)
ET = pytz.timezone("America/New_York")
START_TIME = time.time()

# =========================
# TIME
# =========================
def get_round_info():
    now = int(datetime.now(ET).timestamp())
    end = now - (now % 300)
    countdown = 300 - (now % 300)
    return end, countdown

def get_uptime():
    s = int(time.time() - START_TIME)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

# =========================
# PRICE
# =========================
def get_price(symbol):
    try:
        r = requests.get(f"https://api.exchange.coinbase.com/products/{symbol}/ticker", timeout=5).json()
        return float(r["price"])
    except:
        return None

# =========================
# CLOB
# =========================
def get_clob(token):
    try:
        r = requests.get(f"https://clob.polymarket.com/book?token_id={token}", timeout=5).json()
        bids = r.get("bids", [])
        asks = r.get("asks", [])

        bid_liq = sum(float(b[1]) for b in bids[:5])
        ask_liq = sum(float(a[1]) for a in asks[:5])

        best_bid = float(bids[0][0]) if bids else 0

        return bid_liq, ask_liq, best_bid
    except:
        return None

def get_clob_sentiment(market):
    ids = TOKEN_IDS[market]

    yes = get_clob(ids["yes"])
    no = get_clob(ids["no"])

    if not yes or not no:
        return None, 0, 0

    up = yes[0]
    down = no[0]

    if up > down * 1.2:
        signal = "UP"
    elif down > up * 1.2:
        signal = "DOWN"
    else:
        signal = None

    return signal, round(up,2), round(down,2)

# =========================
# STATE
# =========================
state = {
    m: {
        "history": [],
        "price": None,
        "signal": None,
        "clob": None,
        "up": 0,
        "down": 0,
        "timer": "00:00",
        "bet": "None"
    } for m in markets
}

# =========================
# BOT LOOP
# =========================
def run_market(m):
    s = state[m]
    last_round = None

    while True:
        time.sleep(3)

        end, countdown = get_round_info()

        mins = countdown // 60
        secs = countdown % 60
        s["timer"] = f"{mins:02d}:{secs:02d}"

        price = get_price(symbols[m])
        if not price:
            continue

        s["price"] = price

        clob, up, down = get_clob_sentiment(m)
        s["clob"] = clob
        s["up"] = up
        s["down"] = down

        if last_round is None:
            last_round = end
            s["start"] = price
            continue

        if end != last_round:
            outcome = "UP" if price > s["start"] else "DOWN"

            s["history"].append(outcome)
            if len(s["history"]) > 7:
                s["history"].pop(0)

            if len(s["history"]) >= 3:
                last3 = s["history"][-3:]
                if last3 == ["UP","UP","UP"]:
                    s["signal"] = "DOWN"
                elif last3 == ["DOWN","DOWN","DOWN"]:
                    s["signal"] = "UP"
                else:
                    s["signal"] = None

            if s["signal"] and s["signal"] == s["clob"]:
                s["bet"] = s["signal"]
            else:
                s["bet"] = "None"

            s["start"] = price
            last_round = end

# =========================
# START THREADS
# =========================
started = False

@app.before_request
def start():
    global started
    if not started:
        for m in markets:
            threading.Thread(target=run_market, args=(m,), daemon=True).start()
        started = True

# =========================
# API
# =========================
@app.route("/data")
def data():
    return jsonify({"state": state, "uptime": get_uptime()})

# =========================
# UI
# =========================
HTML = """
<html>
<script>
async function load(){
 let r=await fetch('/data'); let d=await r.json();

 document.getElementById("up").innerText=d.uptime;

 for (const [m,s] of Object.entries(d.state)){
  document.getElementById(m+"_p").innerText=s.price||"-";
  document.getElementById(m+"_sig").innerText=s.signal||"-";
  document.getElementById(m+"_clob").innerText=s.clob||"-";
  document.getElementById(m+"_liq").innerText="UP:"+s.up+" DOWN:"+s.down;
  document.getElementById(m+"_hist").innerText=s.history.join(",");
  document.getElementById(m+"_timer").innerText=s.timer;
  document.getElementById(m+"_bet").innerText=s.bet;
 }
}
setInterval(load,3000);
</script>

<body style="background:#111;color:white">
<h2>Uptime: <span id="up"></span></h2>

{% for m in state %}
<div style="border:1px solid #444;margin:10px;padding:10px">
<h3>{{m}}</h3>
<p>Timer: <span id="{{m}}_timer"></span></p>
<p>Price: <span id="{{m}}_p"></span></p>
<p>Pattern: <span id="{{m}}_sig"></span></p>
<p>CLOB: <span id="{{m}}_clob"></span></p>
<p>Liquidity: <span id="{{m}}_liq"></span></p>
<p>Bet: <span id="{{m}}_bet"></span></p>
<p>History: <span id="{{m}}_hist"></span></p>
</div>
{% endfor %}
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML, state=state)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)