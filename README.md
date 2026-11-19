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
