import time
import re
import requests
from playwright.sync_api import sync_playwright

WEB_APP_URL = "https://trading-dashboard-o3wm.onrender.com/update"

markets = {
    "bitcoin": "https://polymarket.com/event/btc-updown-5m",
    "ethereum": "https://polymarket.com/event/eth-updown-5m",
    "ripple": "https://polymarket.com/event/xrp-updown-5m",
    "solana": "https://polymarket.com/event/sol-updown-5m"
}

def extract(page, url):
    try:
        page.goto(url, timeout=15000)
        page.wait_for_timeout(3000)

        html = page.content()
        matches = re.findall(r'([0]\.[0-9]{2})', html)

        if len(matches) >= 2:
            return float(matches[0]), float(matches[1])
    except:
        pass
    return None, None

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()

        while True:
            payload = {}

            for m, url in markets.items():
                yes, no = extract(page, url)
                payload[m] = {"yes": yes, "no": no}

            try:
                requests.post(WEB_APP_URL, json=payload, timeout=5)
                print("Sent data:", payload)
            except Exception as e:
                print("POST ERROR:", e)

            time.sleep(5)

if __name__ == "__main__":
    run()