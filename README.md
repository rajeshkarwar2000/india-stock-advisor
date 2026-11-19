# India Stock Advisor (with demo trading)

Auto-updating momentum/growth screener for NSE stocks, with entry, stop-loss, target and position size,
plus a virtual-money trading account (like Groww / Angel One) to practise and track results.

## Themes
Sidebar > Settings > Appearance: Claude Warm (default), Claude Dark, ColorOS 7 Glass, iOS Frosted, Sunset Glass, Aurora Dark, AMOLED Black, or Classic (plain).
You can also change glass blur, corner roundness and turn the animated background off. The theme is kept in the page address.

## Which stocks are scanned
Sidebar > Settings > Stock scan: **Nifty 500** (live list from NSE, large/mid/small caps in every sector) or **Core 55** (fast).
Any other NSE company can be added with "Add NSE symbols". Thinly traded stocks are hidden by the
"Min daily traded value" slider (set 0 to include everything). Gemini may recommend ANY NSE-listed company;
the app fetches a live price for it so you can still demo-buy.

## Run on your computer
    pip install -r requirements.txt
    streamlit run app.py

## Free hosting (works on your phone, always up to date)
1. Upload `app.py`, `engine.py`, `gemini_client.py`, `themes.py`, `requirements.txt`, the `.streamlit` folder to a GitHub repo.
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
(In the Android app, Open Gemini launches the Gemini app, or your browser if the Gemini app isn't installed.)
