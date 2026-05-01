# ONLY showing key changes cleanly so you can patch safely

# =========================
# SETTINGS
# =========================
stake_levels = [4, 8, 20, 44, 100]


# =========================
# STATE ADDITION
# =========================
"default_state" update per market:

"max_streak": 0,


# =========================
# STREAK LOGIC UPDATE
# =========================
streak_dir, streak_count = get_streak(s["history"])

# UPDATE MAX STREAK
if streak_count > s["max_streak"]:
    s["max_streak"] = streak_count


# =========================
# RESET BLOCK (WIN)
# =========================
if win:
    profit = prev_bet * 0.75
    bankroll += profit
    s["profit"] += profit

    s["in_trade"] = False
    s["waiting_for_pattern"] = True
    s["trade_direction"] = None
    s["step"] = 0

    # 🔥 CLEAN RESET
    s["history"] = []
    s["signal"] = None
    s["pending"] = False
    s["max_streak"] = 0


# =========================
# RESET BLOCK (FINAL LOSS)
# =========================
if s["step"] >= len(stake_levels):
    bankroll -= prev_bet
    s["profit"] -= prev_bet

    s["in_trade"] = False
    s["waiting_for_pattern"] = True
    s["trade_direction"] = None
    s["step"] = 0

    # 🔥 CLEAN RESET
    s["history"] = []
    s["signal"] = None
    s["pending"] = False
    s["max_streak"] = 0


# =========================
# UI ADD (INSIDE HTML LOOP)
# =========================

<p>Max Streak: <span id="{{m}}_streak">0</span></p>


# =========================
# JS UPDATE
# =========================
document.getElementById(m+"_streak").innerText = s.max_streak;