# India Stock Advisor (with demo trading)

Auto-updating momentum/growth screener for NSE stocks, with entry, stop-loss, target and position size,
plus a virtual-money trading account (like Groww / Angel One) to practise and track results.

## Run on your computer
    pip install -r requirements.txt
    streamlit run app.py

## Free hosting (works on your phone, always up to date)
1. Upload `app.py`, `engine.py`, `requirements.txt` to a GitHub repo.
2. Go to share.streamlit.io, sign in with GitHub, choose the repo, main file `app.py`, Deploy.

## Demo trading
- Starts with Rs 10,00,000 virtual cash (changeable in "Order history & account").
- Tap "Demo buy" on any idea (stop-loss and target are attached), or place an order in the Demo portfolio tab.
- Holdings show LTP, P&L in Rs and %, growth charts per stock, and total portfolio growth.
- Stop-loss / target auto-sell like a bracket order (can be turned off in the sidebar).
- Accounts are saved per "Demo account name". On free cloud hosting they can reset when the app restarts,
  so use Export backup. Running locally keeps them permanently.
- Virtual only: no brokerage, taxes or slippage; fills at the last available price (can be a few minutes delayed).

## Ask Gemini
1. Get a free API key at aistudio.google.com.
2. Paste it in the sidebar ("Gemini API key"), or on Streamlit Cloud add `GEMINI_API_KEY = "..."` under app Settings > Secrets.
3. Open the "Ask Gemini" tab. Gemini gets the app's rankings and your demo holdings as context.
If you see a "model not found" error, update the model name in the sidebar to a current one listed at ai.google.dev.

## GitHub workflow
`.github/workflows/ci.yml` runs on every push: installs dependencies, compile-checks the code and runs the tests in `tests/`.
Deploy for free at share.streamlit.io by pointing it at this repo (main file `app.py`). Never commit your API key;
`.gitignore` already excludes `.streamlit/secrets.toml` and saved demo accounts.

## Ask Gemini without an API key
Open the "Ask Gemini" tab > "Copy & paste". Pick a question, tap Copy prompt, tap Open Gemini, paste the prompt,
then paste Gemini's JSON reply back into the app. The app turns it into cards with a live-price check and a Demo buy button.
(In the Android app, Open Gemini launches the Gemini app or your browser.)

## Themes
Sidebar > Appearance: pick ColorOS 7 Glass (default), Midnight Glass, Aurora, Sunset, Neon Terminal or Classic. Adjust glass blur or turn off the animated background to save battery. The choice is saved with your demo account.

## Any company, research-based ideas
- "Find any stock" searches every NSE/BSE company by name, symbol or BSE code (new listings such as Jio Platforms, NSE: JPL, work too, with a short-history warning).
- Idea cards combine price trend with broker/analyst ratings and targets, institutional holding and results data (revenue, earnings, margins, ROE, debt).
- The Gemini prompt tells Gemini to weigh broker and institutional views, global news and technology shifts, government policy and company results, and lets it pick ANY listed company.
- Appearance has Text size and High contrast options for the clearest text.

## Market scan (any listed company)
The "Market scan" tab downloads NSE's stock list (Nifty 500, plus Microcap 250, or every listed stock), pulls about 14 months of prices and volume,
removes stocks that are too thinly traded or too cheap to be feasible (set by your risk appetite), and ranks the rest by return potential:
3/1/6-month momentum, closeness to the 52-week high, volume surge and trend, plus analyst and results data for the top names.
Results are cached in scan_cache/ so reopening is instant; re-run for fresh prices.

## What's new (Groww-style version)
- **Layout:** four groups. Explore (1 Month / 6 Months / 1 Year ideas, Scan all stocks, Search & watchlist), Portfolio (Holdings cards, Orders, P&L report, Growth, AI review, Account), Gemini AI, Tools.
- **Cards and tags:** every stock is a card with its current price, today's move, tags (1M / 6M / 1Y horizon, BUY / HOLD / SELL, risk, momentum, analyst view) and green/red profit and loss in ₹ and %.
- **Buy / Sell windows:** Delivery or Intraday (sold at 3:20 PM), Market or Limit, quantity, horizon and optional stop-loss and target. Limit orders wait in Portfolio > Orders.
- **Live portfolio:** buy price next to current price, returns in ₹ and %, today's returns, a stop-loss to target bar, live net-worth chart. A countdown at the top shows the time to the next refresh; The top Refresh updates the market; **Refresh portfolio** (with its own timer and interval) updates only your holdings. The countdown pauses while a buy/sell window is open. Change the interval in the sidebar.
- **P&L report:** every closed trade and a per-stock summary. Realised + unrealised always equals net worth minus starting cash (charges ignored).
- **Portfolio review (Gemini):** its own tab: instant rule-based check, a separate Gemini prompt for your holdings (copy & paste, or API key) and action buttons for the reply.
- **Scan all stocks:** every NSE-listed company (~2,000+), with progress and time left; rank by 1M / 6M / 1Y. If NSE's list won't download, upload EQUITY_L.csv.
- Needs Streamlit 1.40 or newer (buy/sell windows).
