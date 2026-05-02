import time
import requests
import os
import threading
from flask import Flask

# =========================
# CONFIG
# =========================
GAMMA_URL = "https://gamma-api.polymarket.com/markets"

BASE_BET = 1.0
TARGET_PROFIT = 0.30
MAX_BET = 5.0
MAX_STEPS = 10

ROUND_WAIT = 320
SLEEP_TIME = 10

# =========================
# SIMULATION STATE
# =========================
bankroll = 100.0

current_loss = 0.0
step = 1
active_trade = False
current_side = None

price_history = []
MAX_HISTORY = 5

# =========================
# FLASK APP
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return f"Bot running | Bankroll: {bankroll:.2f}"

# =========================
# MARKET FUNCTIONS
# =========================
def get_active_markets():
    return requests.get(GAMMA_URL, params={"active": "true", "limit": 100}).json()

def find_market(markets):
    for m in markets:
        q = m["question"].lower()
        if "5 min" in q and ("up" in q or "down" in q):
            return m
    return None

def extract_tokens(market):
    tokens = {}
    for o in market["outcomes"]:
        name = o["name"].lower()
        if "up" in name or "yes" in name:
            tokens["UP"] = o["token_id"]
        elif "down" in name or "no" in name:
            tokens["DOWN"] = o["token_id"]
    return tokens

# =========================
# PRICE (NO CLIENT)
# =========================
def get_price(token_id):
    try:
        url = f"https://clob.polymarket.com/books/{token_id}"
        data = requests.get(url).json()

        asks = data.get("asks", [])
        if not asks:
            return None

        return float(asks[0]["price"])
    except:
        return None

# =========================
# PRICE + STREAK
# =========================
def update_price(price):
    global price_history
    price_history.append(price)
    if len(price_history) > MAX_HISTORY:
        price_history.pop(0)

def detect_streak():
    if len(price_history) < 4:
        return None

    directions = []
    for i in range(1, len(price_history)):
        if price_history[i] > price_history[i - 1]:
            directions.append("UP")
        else:
            directions.append("DOWN")

    last3 = directions[-3:]

    if all(d == "DOWN" for d in last3):
        return "UP"
    if all(d == "UP" for d in last3):
        return "DOWN"

    return None

# =========================
# BET LOGIC
# =========================
def calculate_bet(price):
    global current_loss, step

    if price is None or price <= 0 or price >= 1:
        return BASE_BET

    required = current_loss + TARGET_PROFIT
    raw = required * (price / (1 - price))

    safety = min(1.0, 0.7 + (step / MAX_STEPS) * 0.3)
    bet = min(raw * safety, MAX_BET)

    return max(bet, BASE_BET)

# =========================
# SIMULATED ORDER
# =========================
def place_order(price, bet, side):
    print(f"🧪 SIM BET {side} | ${bet:.2f} at price {price:.3f}")

# =========================
# RESULT (REAL DATA)
# =========================
def get_result(market_id):
    try:
        data = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}").json()

        for o in data["outcomes"]:
            if o.get("winner"):
                name = o["name"].lower()
                if "up" in name or "yes" in name:
                    return "UP"
                else:
                    return "DOWN"
    except:
        return None

    return None

# =========================
# PROCESS RESULT
# =========================
def process(price, won, bet):
    global current_loss, step, active_trade, current_side, bankroll

    if won:
        profit = bet * ((1 - price) / price)
        net = profit - current_loss

        bankroll += profit
        print(f"✅ WIN | +{profit:.2f} | Bankroll: {bankroll:.2f}")

        if net >= TARGET_PROFIT:
            current_loss = 0
            step = 1
            active_trade = False
            current_side = None
            print("🔄 Reset cycle")
        else:
            current_loss -= profit
            step = max(1, step - 2)

    else:
        bankroll -= bet
        current_loss += bet
        step += 1

        print(f"❌ LOSS | -{bet:.2f} | Bankroll: {bankroll:.2f} | Step: {step}")

        if step > MAX_STEPS:
            print("🛑 Max steps reached — reset")
            current_loss = 0
            step = 1
            active_trade = False
            current_side = None

# =========================
# MAIN BOT LOOP
# =========================
def run_bot():
    global active_trade, current_side

    print("🚀 Simulation bot started...")

    while True:
        try:
            markets = get_active_markets()
            market = find_market(markets)

            if not market:
                print("❌ No market found")
                time.sleep(5)
                continue

            tokens = extract_tokens(market)

            ref_token = tokens.get("UP")
            price = get_price(ref_token)

            if price is None:
                time.sleep(2)
                continue

            update_price(price)

            print(f"\n📊 Price: {price:.3f} | Step: {step} | Loss: {current_loss:.2f} | Bankroll: {bankroll:.2f}")

            # WAIT MODE
            if not active_trade:
                signal = detect_streak()

                if signal:
                    active_trade = True
                    current_side = signal
                    print(f"🔥 Enter cycle: {current_side}")
                else:
                    time.sleep(SLEEP_TIME)
                    continue

            # ACTIVE MODE
            token_id = tokens[current_side]
            price = get_price(token_id)

            if price is None:
                time.sleep(2)
                continue

            bet = calculate_bet(price)

            place_order(price, bet, current_side)

            # Wait for resolution
            time.sleep(ROUND_WAIT)

            result = get_result(market["id"])

            if result is None:
                print("⏳ Waiting for resolution...")
                continue

            won = result == current_side
            process(price, won, bet)

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print(f"🔥 Error: {e}")
            time.sleep(5)

# =========================
# START APP
# =========================
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))