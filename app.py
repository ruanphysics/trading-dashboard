import time
import threading
from datetime import datetime
import pytz
import requests
from flask import Flask, jsonify, request, render_template_string

# =========================
# SETTINGS
# =========================
markets = ["bitcoin","ethereum","ripple","solana"]

symbols = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "ripple": "XRP-USD",
    "solana": "SOL-USD"
}

app = Flask(__name__)
ET = pytz.timezone("America/New_York")
START_TIME = time.time()

# 🔥 STORE WORKER DATA HERE
poly_data = {
    m: {"yes": None, "no": None}
    for m in markets
}

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
        r = requests.get(
            f"https://api.exchange.coinbase.com/products/{symbol}/ticker",
            timeout=5
        ).json()
        return float(r["price"])
    except:
        return None

def get_poly_signal(yes, no):
    if yes is None or no is None:
        return None
    if yes > 0.55:
        return "UP"
    elif no > 0.55:
        return "DOWN"
    return None

# =========================
# 🔥 RECEIVE DATA FROM WORKER
# =========================
@app.route("/update", methods=["POST"])
def update():
    data = request.json

    print("RECEIVED:", data)  # 👈 IMPORTANT FOR DEBUG

    for m in markets:
        if m in data:
            poly_data[m]["yes"] = data[m]["yes"]
            poly_data[m]["no"] = data[m]["no"]

    return {"status": "ok"}

# =========================
# STATE
# =========================
state = {
    m: {
        "history": [],
        "price": None,
        "pattern": None,
        "poly": None,
        "yes": None,
        "no": None,
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
        time.sleep(5)

        end, countdown = get_round_info()
        mins = countdown // 60
        secs = countdown % 60
        s["timer"] = f"{mins:02d}:{secs:02d}"

        price = get_price(symbols[m])
        if not price:
            continue

        s["price"] = price

        # 🔥 USE WORKER DATA
        yes = poly_data[m]["yes"]
        no = poly_data[m]["no"]

        s["yes"] = yes
        s["no"] = no
        s["poly"] = get_poly_signal(yes, no)

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
                    s["pattern"] = "DOWN"
                elif last3 == ["DOWN","DOWN","DOWN"]:
                    s["pattern"] = "UP"
                else:
                    s["pattern"] = None

            if s["pattern"] and s["pattern"] == s["poly"]:
                s["bet"] = s["pattern"]
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
    return jsonify({
        "state": state,
        "uptime": get_uptime()
    })

# =========================
# UI
# =========================
HTML = """
<html>
<script>
async function load(){
 let r=await fetch('/data');
 let d=await r.json();

 document.getElementById("up").innerText=d.uptime;

 for (const [m,s] of Object.entries(d.state)){
  document.getElementById(m+"_p").innerText=s.price||"-";
  document.getElementById(m+"_pattern").innerText=s.pattern||"-";
  document.getElementById(m+"_poly").innerText=s.poly||"-";
  document.getElementById(m+"_yes").innerText=s.yes||"-";
  document.getElementById(m+"_no").innerText=s.no||"-";
  document.getElementById(m+"_hist").innerText=s.history.join(",");
  document.getElementById(m+"_timer").innerText=s.timer;
  document.getElementById(m+"_bet").innerText=s.bet;
 }
}
setInterval(load,5000);
</script>

<body style="background:#111;color:white">
<h2>Uptime: <span id="up"></span></h2>

{% for m in state %}
<div style="border:1px solid #444;margin:10px;padding:10px">
<h3>{{m}}</h3>
<p>Timer: <span id="{{m}}_timer"></span></p>
<p>Price: <span id="{{m}}_p"></span></p>
<p>YES: <span id="{{m}}_yes"></span></p>
<p>NO: <span id="{{m}}_no"></span></p>
<p>Pattern: <span id="{{m}}_pattern"></span></p>
<p>Polymarket: <span id="{{m}}_poly"></span></p>
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