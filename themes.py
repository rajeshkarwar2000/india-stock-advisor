"""Switchable glass themes for the Streamlit app (pure CSS, no extra packages).

Each theme is a dict of colours. `css()` turns one into a <style> block. "Classic" returns no CSS at all,
so the app falls back to Streamlit's normal look.
"""
import re

_FONTS = ("@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&"
          "family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap');")
_SERIF = '"Newsreader","Tiempos Headline",Georgia,"Times New Roman",serif'
_SANS = '"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'

THEMES = {
    "Claude Warm": dict(
        dark=False, flat=True, blur=0, radius=16, accent="#C96442", accent2="#C96442", accent_text="#ffffff",
        base="#FAF9F5", blobs=["transparent"] * 4, fh=_SERIF, fb=_SANS, hw="500", br="12px",
        text="#1F1E1D", muted="#6B6A64", card="#FFFFFF", border="rgba(31,30,29,.15)",
        shadow="0 1px 2px rgba(31,30,29,.06)", input="#FFFFFF", side="#F0EEE6", popover="#FFFFFF",
        selbg="rgba(201,100,66,.12)", seltext="#B4532F"),
    "Claude Dark": dict(
        dark=True, flat=True, blur=0, radius=16, accent="#D97757", accent2="#D97757", accent_text="#ffffff",
        base="#262624", blobs=["transparent"] * 4, fh=_SERIF, fb=_SANS, hw="500", br="12px",
        text="#F5F4EE", muted="#A6A39A", card="#30302E", border="rgba(255,255,255,.12)",
        shadow="0 1px 2px rgba(0,0,0,.35)", input="#30302E", side="#1F1E1D", popover="#30302E",
        selbg="rgba(217,119,87,.20)", seltext="#E8957A"),
    "ColorOS 7 Glass": dict(
        dark=False, blur=24, radius=22, accent="#1fbf75", accent2="#12a8d6", accent_text="#ffffff",
        base="linear-gradient(160deg,#e8f2ff 0%,#f3eefc 48%,#fdeee6 100%)",
        blobs=["rgba(110,175,255,.55)", "rgba(175,145,255,.38)", "rgba(255,175,145,.40)", "rgba(80,225,175,.35)"],
        text="#14181f", muted="#5b6573", card="rgba(255,255,255,.52)", border="rgba(255,255,255,.78)",
        shadow="0 10px 32px rgba(70,90,140,.14)", input="rgba(255,255,255,.62)",
        side="rgba(255,255,255,.42)", popover="rgba(255,255,255,.94)"),
    "iOS Frosted": dict(
        dark=False, blur=30, radius=18, accent="#0a84ff", accent2="#5e5ce6", accent_text="#ffffff",
        base="linear-gradient(160deg,#eef2fb 0%,#dfe8f7 100%)",
        blobs=["rgba(10,132,255,.30)", "rgba(255,105,180,.22)", "rgba(94,92,230,.25)", "rgba(52,199,89,.18)"],
        text="#101114", muted="#5f6572", card="rgba(255,255,255,.60)", border="rgba(255,255,255,.85)",
        shadow="0 8px 28px rgba(30,50,100,.12)", input="rgba(255,255,255,.70)",
        side="rgba(255,255,255,.50)", popover="rgba(255,255,255,.96)"),
    "Sunset Glass": dict(
        dark=False, blur=26, radius=24, accent="#ff6b4a", accent2="#ff3d81", accent_text="#ffffff",
        base="linear-gradient(160deg,#fff1e6 0%,#ffe3ec 50%,#efe3ff 100%)",
        blobs=["rgba(255,150,90,.45)", "rgba(255,90,150,.32)", "rgba(160,120,255,.35)", "rgba(255,210,120,.40)"],
        text="#2a1b1f", muted="#7a6168", card="rgba(255,255,255,.50)", border="rgba(255,255,255,.80)",
        shadow="0 10px 30px rgba(160,70,90,.15)", input="rgba(255,255,255,.62)",
        side="rgba(255,255,255,.40)", popover="rgba(255,255,255,.95)"),
    "Aurora Dark": dict(
        dark=True, blur=22, radius=20, accent="#7c5cff", accent2="#00d6b4", accent_text="#ffffff",
        base="linear-gradient(160deg,#0b1020 0%,#141a33 100%)",
        blobs=["rgba(124,92,255,.45)", "rgba(0,214,180,.28)", "rgba(255,92,170,.24)", "rgba(60,140,255,.25)"],
        text="#eef1ff", muted="#a3abd0", card="rgba(255,255,255,.07)", border="rgba(255,255,255,.15)",
        shadow="0 10px 34px rgba(0,0,0,.40)", input="rgba(255,255,255,.09)",
        side="rgba(15,20,45,.55)", popover="rgba(24,30,62,.97)"),
    "AMOLED Black": dict(
        dark=True, blur=16, radius=16, accent="#00e08a", accent2="#00b4d8", accent_text="#03140c",
        base="#000000",
        blobs=["rgba(0,255,150,.12)", "rgba(0,160,255,.10)", "rgba(160,90,255,.10)", "rgba(0,255,150,.06)"],
        text="#f2f2f2", muted="#9aa0a6", card="rgba(255,255,255,.055)", border="rgba(255,255,255,.11)",
        shadow="0 8px 26px rgba(0,0,0,.6)", input="rgba(255,255,255,.08)",
        side="rgba(10,10,10,.70)", popover="rgba(22,22,22,.98)"),
    "Classic (plain)": dict(css=False),
}
DEFAULT = "Claude Warm"

_CSS = """
__FONTS__:root{color-scheme:__SCHEME__;--text:__TEXT__;--muted:__MUTED__;--card:__CARD__;--border:__BORDER__;
--accent:__ACCENT__;--accent2:__ACCENT2__;--accent-text:__ACCENTTEXT__;--blur:__BLUR__px;--r:__R__px;
--fh:__FH__;--fb:__FB__;--hw:__HW__;--br:__BR__;--selbg:__SELBG__;--seltext:__SELTEXT__;--shadow:__SHADOW__;--input:__INPUT__;--side:__SIDE__;--pop:__POP__;}
.stApp{background:__BASE__ !important;color:var(--text);}
.stApp::before{content:"";position:fixed;inset:-12%;z-index:0;pointer-events:none;background:__BLOBS__;__ANIM__}
@keyframes osdrift{0%{transform:translate3d(0,0,0) scale(1)}100%{transform:translate3d(-3%,2.5%,0) scale(1.1)}}
@media (prefers-reduced-motion:reduce){.stApp::before{animation:none !important}}
[data-testid="stAppViewContainer"],[data-testid="stMain"],.main{background:transparent !important;position:relative;z-index:1;}
[data-testid="stHeader"],[data-testid="stBottom"],[data-testid="stBottom"]>div{background:transparent !important;}
[data-testid="stSidebar"]{background:var(--side) !important;backdrop-filter:blur(var(--blur)) saturate(1.5);
-webkit-backdrop-filter:blur(var(--blur)) saturate(1.5);border-right:1px solid var(--border);z-index:2;}
[data-testid="stSidebar"]>div{background:transparent !important;}
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,.stApp h6,.stApp label,.stApp li,
.stApp [data-testid="stMarkdownContainer"] p,.stApp [data-testid="stMetricValue"],.stApp [data-testid="stMetricLabel"],
.stApp [data-testid="stWidgetLabel"] p{color:var(--text) !important;}
.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stCaptionContainer"] p,.stApp small{color:var(--muted) !important;}
.stApp,.stApp button,.stApp input,.stApp textarea,.stApp [data-baseweb]{font-family:var(--fb);}
.stApp h1,.stApp h2,.stApp h3{font-family:var(--fh) !important;}
.stApp h1{font-weight:var(--hw);letter-spacing:-.02em;}
.stApp hr{border-color:var(--border) !important;}
[class*="st-key-card"],[data-testid="stMetric"],[data-testid="stExpander"],[data-testid="stAlert"],
[data-testid="stChatMessage"],[data-testid="stForm"]{background:var(--card) !important;border:1px solid var(--border) !important;
border-radius:var(--r) !important;box-shadow:var(--shadow),inset 0 1px 0 rgba(255,255,255,.35);
backdrop-filter:blur(var(--blur)) saturate(1.6);-webkit-backdrop-filter:blur(var(--blur)) saturate(1.6);}
[class*="st-key-card"]{padding:14px 16px !important;}
[data-testid="stMetric"]{padding:12px 16px;}
[data-testid="stAlert"] *,[data-testid="stExpander"] summary,[data-testid="stExpander"] summary *{color:var(--text) !important;}
[data-testid="stExpander"] details{border:0 !important;background:transparent !important;}
.stTabs [data-baseweb="tab-list"]{background:var(--card);border:1px solid var(--border);border-radius:999px;padding:4px;gap:2px;
backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));overflow-x:auto;}
.stTabs [data-baseweb="tab"]{border-radius:999px;height:38px;padding:0 14px;background:transparent;}
.stTabs [data-baseweb="tab"] p{color:var(--muted) !important;font-weight:600;}
.stTabs [aria-selected="true"]{background:var(--selbg) !important;}
.stTabs [aria-selected="true"] p{color:var(--seltext) !important;}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none !important;}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button,[data-testid^="stBaseLinkButton"],[data-testid="stLinkButton"] a{
border-radius:var(--br) !important;border:1px solid var(--border) !important;background:var(--card) !important;color:var(--text) !important;
font-weight:500;backdrop-filter:blur(var(--blur));-webkit-backdrop-filter:blur(var(--blur));transition:transform .15s ease,box-shadow .15s ease;}
.stButton>button p,.stFormSubmitButton>button p,.stDownloadButton>button p,[data-testid^="stBaseLinkButton"] p{color:inherit !important;}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover,[data-testid^="stBaseLinkButton"]:hover{
transform:translateY(-1px);box-shadow:var(--shadow);border-color:var(--accent) !important;}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"],[data-testid="stBaseLinkButton-primary"]{
background:linear-gradient(135deg,var(--accent),var(--accent2)) !important;color:var(--accent-text) !important;border-color:transparent !important;}
.stButton>button[kind="primary"] p{color:var(--accent-text) !important;}
input,textarea,[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{
background:var(--input) !important;color:var(--text) !important;-webkit-text-fill-color:var(--text);
border-radius:calc(var(--r)*.6) !important;border-color:var(--border) !important;}
[data-baseweb="select"] *{color:var(--text) !important;}
[data-testid="stChatInput"]{background:var(--input) !important;border-radius:var(--r) !important;}
[data-baseweb="popover"]>div,[data-baseweb="menu"],[data-baseweb="popover"] ul{background:var(--pop) !important;border-radius:calc(var(--r)*.6) !important;}
[data-baseweb="popover"] li,[data-baseweb="popover"] li *{color:var(--text) !important;}
[data-testid^="stBaseButton-pills"],button[kind="pills"],button[kind="pillsActive"]{border-radius:999px !important;background:var(--card) !important;
border:1px solid var(--border) !important;color:var(--text) !important;font-weight:500;}
[data-testid="stBaseButton-pillsActive"],button[kind="pillsActive"]{background:var(--selbg) !important;border-color:var(--accent) !important;color:var(--seltext) !important;}
[data-testid^="stBaseButton-pills"] p,button[kind="pills"] p,button[kind="pillsActive"] p{color:inherit !important;}
[data-testid="stSlider"] [role="slider"]{background:var(--accent) !important;box-shadow:0 0 0 4px rgba(127,127,127,.18);}
[data-testid="stDataFrame"],[data-testid="stVegaLiteChart"],[data-testid="stArrowVegaLiteChart"]{border-radius:calc(var(--r)*.6);overflow:hidden;__DARKFIX__}
code,pre{border-radius:calc(var(--r)*.5) !important;}
"""


def css(name, blur=None, radius=None, animate=True):
    """Return a minified <style> block for the theme, or '' for the Classic (plain) look."""
    t = THEMES.get(name) or THEMES[DEFAULT]
    if t.get("css") is False:
        return ""
    b = t["blobs"]
    blobs = ",".join([
        f"radial-gradient(40vmax 40vmax at 12% 8%,{b[0]},transparent 62%)",
        f"radial-gradient(46vmax 46vmax at 92% 18%,{b[1]},transparent 62%)",
        f"radial-gradient(52vmax 52vmax at 70% 96%,{b[2]},transparent 62%)",
        f"radial-gradient(36vmax 36vmax at 4% 86%,{b[3]},transparent 62%)"])
    vals = {
        "SCHEME": "dark" if t["dark"] else "light", "TEXT": t["text"], "MUTED": t["muted"], "CARD": t["card"],
        "BORDER": t["border"], "ACCENTTEXT": t["accent_text"], "ACCENT2": t["accent2"], "ACCENT": t["accent"],
        "BLUR": str(int(t["blur"] if blur is None else blur)), "R": str(int(t["radius"] if radius is None else radius)),
        "SHADOW": t["shadow"], "INPUT": t["input"], "SIDE": t["side"], "POP": t["popover"], "BASE": t["base"],
        "BLOBS": blobs, "ANIM": "animation:osdrift 26s ease-in-out infinite alternate;" if animate and not t.get("flat") else "",
        "FONTS": _FONTS if t.get("flat") else "", "FH": t.get("fh", "inherit"), "FB": t.get("fb", "inherit"),
        "HW": t.get("hw", "800"), "BR": t.get("br", "999px"),
        "SELBG": t.get("selbg", f"linear-gradient(135deg,{t['accent']},{t['accent2']})"), "SELTEXT": t.get("seltext", t["accent_text"]),
        # Streamlit's tables/charts draw on a canvas that ignores CSS colours, so flip them for dark themes.
        "DARKFIX": "filter:invert(.92) hue-rotate(180deg);" if t["dark"] else ""}
    out = _CSS
    for k, v in vals.items():
        out = out.replace(f"__{k}__", v)
    return "<style>" + re.sub(r"\s+", " ", out).strip() + "</style>"
