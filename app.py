# ONLY showing the IMPORTANT FIXED PART (your structure stays the same)

def run_market(m):
    global bankroll
    s = state[m]

    last_round_end = None

    while True:
        try:
            time.sleep(1)  # 🔥 faster loop for precision

            start, end = get_round_times()

            next_start = end
            next_end = end + 300

            s["round"] = f"{datetime.fromtimestamp(next_start, ET).strftime('%H:%M')} → {datetime.fromtimestamp(next_end, ET).strftime('%H:%M')}"
            s["countdown"] = get_countdown_seconds()

            price = get_coinbase_price(symbols[m])
            if price is None:
                continue

            s["current_price"] = price

            if last_round_end is None:
                last_round_end = end
                s["start_price"] = price
                continue

            # 🔥 ROUND GUARD (prevents double processing)
            if s.get("last_processed_end") == end:
                continue

            # 🔥 ONLY process EXACTLY on new round
            if end > last_round_end:

                s["last_processed_end"] = end
                end_price = price

                # clear pending instantly
                s["pending"] = False

                if end_price > s["start_price"]:
                    outcome = "UP"
                elif end_price < s["start_price"]:
                    outcome = "DOWN"
                else:
                    outcome = "FLAT"

                # HISTORY
                if outcome != "FLAT":
                    s["history"].append(outcome)
                    if len(s["history"]) > 7:
                        s["history"].pop(0)

                # SIGNAL
                if len(s["history"]) >= 3:
                    last3 = s["history"][-3:]
                    if last3 == ["UP","UP","UP"]:
                        s["signal"] = "DOWN"
                    elif last3 == ["DOWN","DOWN","DOWN"]:
                        s["signal"] = "UP"
                    else:
                        s["signal"] = None

                # ENTER TRADE
                if s["signal"] and not s["in_trade"]:
                    s["in_trade"] = True
                    s["trade_direction"] = s["signal"]
                    s["step"] = 0
                    s["just_entered"] = True
                    s["pending"] = True

                # EXECUTION
                if s["in_trade"]:
                    bet = stake_levels[s["step"]]
                    s["bet"] = bet

                    if s["just_entered"]:
                        s["just_entered"] = False
                    else:
                        win = (
                            (s["trade_direction"] == "UP" and outcome == "UP") or
                            (s["trade_direction"] == "DOWN" and outcome == "DOWN")
                        )

                        if win:
                            profit = bet * 0.75
                            with bankroll_lock:
                                bankroll += profit
                            s["profit"] += profit

                            s["in_trade"] = False
                            s["signal"] = None
                            s["trade_direction"] = None
                            s["step"] = 0

                        else:
                            loss = bet
                            with bankroll_lock:
                                bankroll -= loss
                            s["profit"] -= loss

                            s["step"] += 1

                            if s["step"] >= len(stake_levels):
                                s["in_trade"] = False
                                s["signal"] = None
                                s["trade_direction"] = None
                                s["step"] = 0
                            else:
                                s["just_entered"] = True
                                s["pending"] = True

                s["start_price"] = price
                last_round_end = end
                save_state()

            s["last_update"] = datetime.now(ET).strftime("%H:%M:%S")

        except Exception as e:
            print("ERROR:", e)