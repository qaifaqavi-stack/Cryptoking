"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   CRYPTO BOT V10 · TIERED SL + LIQUIDITY TP EDITION                       ║
║   ICT Order Block · Demand/Supply Zones · Break of Structure              ║
║   Tiered SL System (Tier1→Tier2→Tier3→WorstCase→HOLD)                     ║
║   Liquidity-Based TP (BSL/SSL pools — not ATR)                            ║
║   $100 Wallet · $10 Margin · 20x Leverage · 4.5% Liquidation             ║
║   5-User Login · 4-Tab UI · 8 Bugs Fixed from V9                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

PHILOSOPHY:
  - Accuracy over frequency
  - TP = nearest liquidity pool (where price IS going), not ATR guess
  - Every trade must have R:R ≥ 2.0
  - HOLD is correct behavior when no clear path exists
  - $200 position ($10 margin × 20x) — liquidation at 4.5%, SL max 2%
"""

import streamlit as st
import os, time, queue, warnings, threading
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Lightweight ML Only ──────────────────────────────────────────────────────
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error

try:
    from xgboost import XGBRegressor
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMRegressor
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

import ccxt
import ta

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════════════════
# WALLET CONFIG — V10 Philosophy: $100 wallet, $10 margin, 20x leverage
# ══════════════════════════════════════════════════════════════════════════════
WALLET_CONFIG = {
    "total_balance":    100,    # USD total wallet
    "margin_per_trade": 10,     # USD margin per trade
    "leverage":         20,     # 20x leverage
    "position_size":    200,    # margin * leverage = $200 exposure
    "max_sl_pct":       2.0,    # hard cap — never exceed
    "liquidation_pct":  4.5,    # actual liquidation (1/20 - 0.5% maintenance)
    "max_concurrent":   2,      # max 2 trades open at once
    "daily_loss_limit": 20,     # USD — stop trading if hit
}

# Fee & slippage configuration
FEES = {
    "taker": 0.0006,   # 0.06% Binance futures taker fee
    "slippage": 0.0002 # 0.02% estimated slippage
}
TOTAL_FEE_PCT = (FEES["taker"] + FEES["slippage"]) * 2  # entry + exit

TIER_COLORS = {
    "TIER_1":     {"bg": "#0d2818", "border": "#2ea043", "text": "#56d364"},
    "TIER_2":     {"bg": "#1a2010", "border": "#3fb950", "text": "#3fb950"},
    "TIER_3":     {"bg": "#1c2010", "border": "#f0883e", "text": "#f0883e"},
    "WORST_CASE": {"bg": "#2d1a00", "border": "#f0883e", "text": "#ffa657"},
    "HOLD":       {"bg": "#161b22", "border": "#30363d", "text": "#8b949e"},
}

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN SYSTEM — 5 Users (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

USERS = {
    "zafariqbal@": _hash("pass1234"),
    "mrssher":     _hash("pass2234"),
    "user3":       _hash("pass3234"),
    "trader1":     _hash("trade@123"),
    "admin":       _hash("admin@999"),
}

def login_screen():
    st.markdown("""
    <style>
        .login-title { text-align:center; font-size:2rem; font-weight:bold;
                       color:#58a6ff; margin-bottom:0.3rem; }
        .login-sub   { text-align:center; color:#8b949e; font-size:0.95rem;
                       margin-bottom:1.5rem; }
        .login-wallet { text-align:center; color:#3fb950; font-size:0.85rem;
                        background:#0d2818; padding:8px; border-radius:6px;
                        margin-bottom:1rem; border:1px solid #2ea043; }
    </style>""", unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown('<div class="login-title">🐋 Crypto Bot V10</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">Tiered SL · Liquidity TP · $100 Wallet · 20x</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="login-wallet">💼 $100 Wallet | $10 Margin | 20x Leverage | $200 Position</div>',
                    unsafe_allow_html=True)
        st.markdown("---")
        username = st.text_input("👤 Username", placeholder="Enter username")
        password = st.text_input("🔒 Password", type="password", placeholder="Enter password")
        btn = st.button("🔐 Login", use_container_width=True)
        if btn:
            if username in USERS and USERS[username] == _hash(password):
                st.session_state["authenticated"] = True
                st.session_state["current_user"]  = username
                st.success(f"✅ Welcome, **{username}**!")
                st.rerun()
            else:
                st.error("❌ Invalid username or password.")
        st.markdown("---")
        st.caption("🔑 Contact admin for credentials.")

def check_auth():
    return st.session_state.get("authenticated", False)

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Crypto Bot V10",
    page_icon="🐋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stMetric { background-color: #0d1117; border-radius: 8px; padding: 10px; }
    div[data-testid="stMetricValue"] { color: #58a6ff; }
    .stButton button { background-color: #238636; color: white; border: none; }
    .signal-buy   { color: #2ea043; font-size: 1.6rem; font-weight: bold; }
    .signal-sell  { color: #f85149; font-size: 1.6rem; font-weight: bold; }
    .signal-hold  { color: #8b949e; font-size: 1.6rem; font-weight: bold; }
    .tier-badge   { display:inline-block; padding:4px 12px; border-radius:12px;
                    font-weight:bold; font-size:0.9rem; margin-left:12px; }
    .ob-bull-box  { background:#0d2818; border-left:4px solid #2ea043;
                    padding:8px; border-radius:6px; margin:4px 0; }
    .ob-bear-box  { background:#2d0f0f; border-left:4px solid #f85149;
                    padding:8px; border-radius:6px; margin:4px 0; }
    .wallet-card  { background:#0d1117; border:1px solid #21262d; border-radius:8px;
                    padding:12px; margin:4px 0; }
    .liquidity-arrow { color:#58a6ff; font-size:1.2rem; }
    .tier-box     { border-radius:8px; padding:10px 14px; margin:3px 0;
                    border-left:4px solid; }
</style>""", unsafe_allow_html=True)

# ── Auth Gate ────────────────────────────────────────────────────────────────
if not check_auth():
    login_screen()
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════
class Logger:
    def __init__(self):
        self.msgs = []
    def info(self, m):    self.msgs.append(("ℹ️", m))
    def success(self, m): self.msgs.append(("✅", m))
    def warning(self, m): self.msgs.append(("⚠️", m))
    def error(self, m):   self.msgs.append(("❌", m))
    def text(self):
        return "\n".join(f"{i} {m}" for i, m in self.msgs)
    def clear(self):
        self.msgs = []

if "logger" not in st.session_state:
    st.session_state.logger = Logger()
log = st.session_state.logger

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def get_config():
    user = st.session_state.get("current_user", "user")
    col_a, col_b = st.sidebar.columns([2, 1])
    col_a.markdown(f"👤 **{user}**")
    if col_b.button("Logout"):
        st.session_state["authenticated"] = False
        st.session_state["current_user"]  = ""
        st.rerun()

    st.sidebar.header("⚙️ Configuration")
    coin    = st.sidebar.text_input("Coin Symbol", "BTC/USDT")
    tf_main = st.sidebar.selectbox("Main Timeframe", ["1h","4h","15m","30m"], index=0)
    tf_htf  = st.sidebar.selectbox("Higher Timeframe", ["4h","1d","1h"], index=0)

    st.sidebar.markdown("---")
    st.sidebar.subheader("💼 Wallet (V10 Fixed)")
    st.sidebar.info(
        f"💵 Balance: **${WALLET_CONFIG['total_balance']}**  \n"
        f"📦 Margin/Trade: **${WALLET_CONFIG['margin_per_trade']}**  \n"
        f"⚡ Leverage: **{WALLET_CONFIG['leverage']}x**  \n"
        f"📊 Position: **${WALLET_CONFIG['position_size']}**  \n"
        f"🔴 Liq Distance: **{WALLET_CONFIG['liquidation_pct']}%**  \n"
        f"🛡 Max SL: **{WALLET_CONFIG['max_sl_pct']}%**"
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Tier SL Thresholds")
    st.sidebar.caption("Tier 1: ≤ 0.5%  |  Tier 2: ≤ 1.0%  |  Tier 3: ≤ 1.5%  |  Worst: ≤ 2.0%")
    st.sidebar.caption("Min R:R = 2.0 (hardcoded)")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🐋 Whale Settings")
    wvt = st.sidebar.slider("Whale Vol Threshold", 2.0, 5.0, 3.0, 0.5)
    wpm = st.sidebar.slider("Whale Min Move (%)", 0.1, 1.0, 0.3, 0.1) / 100

    st.sidebar.markdown("---")
    st.sidebar.subheader("📦 Order Block Settings")
    ob_lookback = st.sidebar.slider("OB Lookback Candles", 50, 200, 100, 10)
    ob_min_move = st.sidebar.slider("OB Min Impulse (%)", 0.5, 3.0, 1.0, 0.1) / 100

    st.sidebar.markdown("---")
    st.sidebar.subheader("🧠 Model Settings")
    seq_len   = st.sidebar.slider("Sequence Length", 30, 120, 60, 10)
    use_cache = st.sidebar.checkbox("Use Model Cache", True)

    return {
        "COIN": coin, "TF": tf_main, "HTF": tf_htf,
        "BALANCE": WALLET_CONFIG["total_balance"],
        "MARGIN":  WALLET_CONFIG["margin_per_trade"],
        "LEVERAGE": WALLET_CONFIG["leverage"],
        "POSITION": WALLET_CONFIG["position_size"],
        "MAX_SL_PCT": WALLET_CONFIG["max_sl_pct"],
        "LIQ_PCT":  WALLET_CONFIG["liquidation_pct"],
        "MIN_RR":   2.0,
        "WHALE_VOL_THRESH": wvt, "WHALE_MOVE_MIN": wpm,
        "OB_LOOKBACK": ob_lookback, "OB_MIN_MOVE": ob_min_move,
        "SEQ_LEN": seq_len, "USE_CACHE": use_cache,
        "OB_DEPTH": 20, "WALL_MULT": 5.0,
        "STRUCT_LOOKBACK": 75, "STRUCT_MIN_SWING": 0.008,
    }

cfg = get_config()

# ══════════════════════════════════════════════════════════════════════════════
# DATA ENGINE (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
EXCHANGES = ["binance","bybit","okx","kucoin","gateio","mexc"]

@st.cache_resource(show_spinner=False)
def build_exchange_pool():
    pool = {}
    for name in EXCHANGES:
        try:
            pool[name] = getattr(ccxt, name)({"enableRateLimit": True})
        except Exception:
            pass
    return pool

ex_pool = build_exchange_pool()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_ohlcv(symbol: str, tf: str) -> pd.DataFrame:
    limit   = 500 if tf in ("4h","1d") else 1000
    results = []
    q        = queue.Queue()
    stop_evt = threading.Event()

    def _fetch_one(name, ex):
        if stop_evt.is_set():
            return
        try:
            data = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            df   = pd.DataFrame(data, columns=["ts","open","high","low","close","volume"])
            df["ts"]   = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df["_src"] = name
            if len(df) >= 60:
                q.put(df)
        except Exception:
            pass

    threads   = []
    sorted_ex = sorted(ex_pool.items(), key=lambda x: x[0])[:4]
    for name, ex in sorted_ex:
        t = threading.Thread(target=_fetch_one, args=(name, ex), daemon=True)
        t.start()
        threads.append(t)

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            df = q.get(timeout=0.5)
            results.append(df)
            if len(results) >= 2:
                stop_evt.set()
                break
        except queue.Empty:
            if all(not t.is_alive() for t in threads):
                break

    if not results:
        raise RuntimeError(f"No data for {symbol} [{tf}]")

    combined = pd.concat(results).sort_values("ts")
    n_src    = combined["_src"].nunique()

    if n_src > 1:
        def _agg(g):
            vol = g["volume"].values
            w   = vol if vol.sum() > 0 else np.ones(len(g))
            return pd.Series({
                "open":   np.average(g["open"],  weights=w),
                "high":   np.average(g["high"],  weights=w),
                "low":    np.average(g["low"],   weights=w),
                "close":  np.average(g["close"], weights=w),
                "volume": float(np.median(vol)),
            })
        merged = (combined.groupby("ts", sort=True).apply(_agg)
                  .reset_index().rename(columns={"ts": "timestamp"}))
    else:
        merged = (combined.drop_duplicates("ts", keep="last")
                  .drop(columns=["_src"], errors="ignore")
                  .rename(columns={"ts": "timestamp"})
                  .reset_index(drop=True))

    q1, q3 = merged["volume"].quantile([0.25, 0.75])
    cap     = q3 + 5 * (q3 - q1)
    merged["volume"] = merged["volume"].clip(upper=cap)

    for col in ["open","high","low","close","volume"]:
        merged[col] = merged[col].interpolate("linear").ffill().bfill()

    log.success(f"✓ {symbol} [{tf}]: {len(merged)} candles, {n_src} sources")
    return merged.reset_index(drop=True)

# ══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
def _supertrend(df, period=10, mult=3.0):
    atr   = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=period, fillna=True).average_true_range()
    hl2   = (df["high"] + df["low"]) / 2
    upper = (hl2 + mult * atr).values
    lower = (hl2 - mult * atr).values
    close = df["close"].values
    n     = len(close)
    fu, fl    = upper.copy(), lower.copy()
    st_line   = np.zeros(n)
    direction = np.ones(n)
    for i in range(1, n):
        fu[i] = (upper[i] if upper[i] < fu[i-1] or close[i-1] > fu[i-1] else fu[i-1])
        fl[i] = (lower[i] if lower[i] > fl[i-1] or close[i-1] < fl[i-1] else fl[i-1])
        if st_line[i-1] == fu[i-1]:
            st_line[i] = fl[i] if close[i] > fu[i] else fu[i]
        else:
            st_line[i] = fu[i] if close[i] < fl[i] else fl[i]
        direction[i] = 1 if st_line[i] == fl[i] else -1
    df["Supertrend"] = st_line
    df["ST_Dir"]     = direction
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA9"]   = df["close"].ewm(span=9,   adjust=False).mean()
    df["EMA21"]  = df["close"].ewm(span=21,  adjust=False).mean()
    df["EMA50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["SMA20"]  = df["close"].rolling(20).mean()

    typ       = (df["high"] + df["low"] + df["close"]) / 3
    df["VWAP"] = ((typ * df["volume"]).cumsum()
                  / df["volume"].cumsum().replace(0, np.nan))

    df["RSI"] = ta.momentum.RSIIndicator(df["close"], window=14, fillna=True).rsi()
    macd = ta.trend.MACD(df["close"], fillna=True)
    df["MACD"]      = macd.macd()
    df["MACD_Sig"]  = macd.macd_signal()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Sig"]

    stoch = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"], window=14, smooth_window=3, fillna=True)
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()

    df["WilliamsR"] = ta.momentum.WilliamsRIndicator(
        df["high"], df["low"], df["close"], lbp=14, fillna=True).williams_r()
    df["CCI"] = ta.trend.CCIIndicator(
        df["high"], df["low"], df["close"], window=20, fillna=True).cci()
    df["ROC"] = df["close"].pct_change(10).fillna(0)

    df["ATR"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14, fillna=True).average_true_range()
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2, fillna=True)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Mid"]   = bb.bollinger_mavg()
    df["BB_Width"] = ((df["BB_Upper"] - df["BB_Lower"])
                      / df["BB_Mid"].replace(0, np.nan)).fillna(0)
    df["BB_Pos"]   = ((df["close"] - df["BB_Lower"])
                      / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)).fillna(0.5)

    atr_vals = df["ATR"].values
    ap = np.full(len(atr_vals), 50.0)
    w  = min(100, len(atr_vals))
    for i in range(w, len(atr_vals)):
        ap[i] = np.sum(atr_vals[i-w:i] < atr_vals[i]) / w * 100
    df["ATR_Pct"] = ap

    df["OBV"]     = ta.volume.OnBalanceVolumeIndicator(
        df["close"], df["volume"], fillna=True).on_balance_volume()
    df["Vol_MA20"]  = df["volume"].rolling(20).mean().bfill()
    df["Vol_Ratio"] = (df["volume"] / df["Vol_MA20"].replace(0, np.nan)).fillna(1).clip(0, 10)
    df["Vol_Delta"] = np.where(df["close"] >= df["open"], df["volume"], -df["volume"])
    df["CVD20"]     = df["Vol_Delta"].rolling(20).sum()

    vol_vals = df["volume"].values
    vp = np.full(len(vol_vals), 50.0)
    for i in range(w, len(vol_vals)):
        vp[i] = np.sum(vol_vals[i-w:i] < vol_vals[i]) / w * 100
    df["Vol_Pct"] = vp

    adx_i = ta.trend.ADXIndicator(
        df["high"], df["low"], df["close"], window=14, fillna=True)
    df["ADX"]     = adx_i.adx()
    df["ADX_Pos"] = adx_i.adx_pos()
    df["ADX_Neg"] = adx_i.adx_neg()

    df = _supertrend(df)

    body = (df["close"] - df["open"]).abs()
    rng  = (df["high"] - df["low"]).replace(0, np.nan)
    df["Body_Ratio"]    = (body / rng).fillna(0)
    df["Upper_Wick"]    = (df["high"] - df[["close","open"]].max(axis=1)) / rng.fillna(1)
    df["Lower_Wick"]    = (df[["close","open"]].min(axis=1) - df["low"]) / rng.fillna(1)
    df["Price_vs_VWAP"] = (df["close"] - df["VWAP"]) / df["VWAP"].replace(0, np.nan)
    df["EMA_Spread"]    = (df["EMA9"] - df["EMA50"]) / df["EMA50"].replace(0, np.nan)
    df["Momentum_5"]    = df["close"].pct_change(5).fillna(0)
    df["Momentum_20"]   = df["close"].pct_change(20).fillna(0)

    atr_norm   = (df["ATR"] / df["close"].rolling(20).mean()).fillna(0).clip(0, 1)
    df["RSI_Lo"] = 30 + atr_norm * 10
    df["RSI_Hi"] = 70 - atr_norm * 10

    df = df.dropna(subset=["EMA200","ADX","ATR"]).reset_index(drop=True)
    log.info(f"📊 Indicators: {len(df)} candles, {len(df.columns)} features")
    return df

# ══════════════════════════════════════════════════════════════════════════════
# ORDER BLOCK DETECTION — V10 (Bug 4 Fixed: 3-candle mitigation)
# Bug A Fix: mitigation now checks 3 closes after the OB candle, not global last.
# ══════════════════════════════════════════════════════════════════════════════
def detect_order_blocks(df: pd.DataFrame):
    """
    ICT / Smart Money Order Block Detection.
    Bug 4 Fix: mitigation requires 3 consecutive closes after the OB candle.
    Bug A Fix: use closes from after the OB candle, not global last 3.
    """
    lookback = cfg["OB_LOOKBACK"]
    min_move = cfg["OB_MIN_MOVE"]

    if len(df) < 30:
        return [], []

    rec = df.tail(lookback).reset_index(drop=True)
    n   = len(rec)
    bull_obs, bear_obs = [], []

    for i in range(1, n - 4):
        c_open  = float(rec["open"].iloc[i])
        c_close = float(rec["close"].iloc[i])
        c_high  = float(rec["high"].iloc[i])
        c_low   = float(rec["low"].iloc[i])
        volume  = float(rec["volume"].iloc[i])
        vol_ma  = float(rec["Vol_MA20"].iloc[i]) if "Vol_MA20" in rec.columns else volume

        # ── Bullish OB: bearish candle before upward impulse ──────────────
        if c_close < c_open:
            window = min(i + 6, n)
            future_high = rec["high"].iloc[i+1:window].max()
            impulse = (future_high - c_close) / max(c_close, 1e-10)
            if impulse >= min_move:
                ob_bottom = c_low
                # Bug A Fix: check 3 closes AFTER this OB candle
                post_ob_closes = rec["close"].iloc[i+1:i+4].values
                mitigated = (len(post_ob_closes) >= 3 and
                             all(c < ob_bottom * 0.999 for c in post_ob_closes))
                bull_obs.append({
                    "idx":         i,
                    "ob_top":      round(c_open, 8),
                    "ob_bottom":   round(c_low,  8),
                    "sl_level":    round(c_low * 0.998, 8),
                    "timestamp":   rec["timestamp"].iloc[i],
                    "impulse_pct": round(impulse * 100, 2),
                    "vol_ratio":   round(volume / max(vol_ma, 1e-10), 2),
                    "mitigated":   mitigated,
                    "type":        "BULLISH_OB",
                    "label":       "🟢 Demand Zone",
                })

        # ── Bearish OB: bullish candle before downward impulse ────────────
        elif c_close > c_open:
            window = min(i + 6, n)
            future_low = rec["low"].iloc[i+1:window].min()
            impulse = (c_close - future_low) / max(c_close, 1e-10)
            if impulse >= min_move:
                ob_top = c_high
                post_ob_closes = rec["close"].iloc[i+1:i+4].values
                mitigated = (len(post_ob_closes) >= 3 and
                             all(c > ob_top * 1.001 for c in post_ob_closes))
                bear_obs.append({
                    "idx":         i,
                    "ob_top":      round(c_high, 8),
                    "ob_bottom":   round(c_open, 8),
                    "sl_level":    round(c_high * 1.002, 8),
                    "timestamp":   rec["timestamp"].iloc[i],
                    "impulse_pct": round(impulse * 100, 2),
                    "vol_ratio":   round(volume / max(vol_ma, 1e-10), 2),
                    "mitigated":   mitigated,
                    "type":        "BEARISH_OB",
                    "label":       "🔴 Supply Zone",
                })

    active_bull = [ob for ob in bull_obs if not ob["mitigated"]][-5:]
    active_bear = [ob for ob in bear_obs if not ob["mitigated"]][-5:]

    log.info(f"📦 OBs — Bullish: {len(active_bull)}, Bearish: {len(active_bear)}")
    return active_bull, active_bear

def detect_bos(df: pd.DataFrame, structure: dict):
    if not structure or structure["type"] in ("UNKNOWN",):
        return "NONE", "No BOS"
    price     = float(df["close"].iloc[-1])
    prev_high = structure.get("prev_high")
    prev_low  = structure.get("prev_low")
    if prev_high and price > prev_high * 1.002:
        return "BOS_UP",   f"🔼 BOS Up — broke {prev_high:.5f}"
    if prev_low  and price < prev_low  * 0.998:
        return "BOS_DOWN", f"🔽 BOS Down — broke {prev_low:.5f}"
    if structure.get("breakout"):
        return "BOS_UP",   "🔼 Breakout confirmed"
    if structure.get("breakdown"):
        return "BOS_DOWN", "🔽 Breakdown confirmed"
    return "NONE", "No BOS yet"

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDITY TP SYSTEM — V10 Core Philosophy
# Bug B Fix: optimized equal highs detection (O(n²) → O(n log n))
# Bug C Fix: Tier 2 distance logic corrected (absolute distance)
# ══════════════════════════════════════════════════════════════════════════════
def find_nearest_liquidity(price: float, direction: str,
                            df: pd.DataFrame,
                            bull_obs: list, bear_obs: list,
                            structure: dict, sl_pct: float):
    """
    Find nearest valid liquidity pool for TP.
    Pools: Equal Highs/Lows, Swing Highs/Lows, Unmitigated OB tops/bottoms.
    Returns level only if it gives R:R >= 2.0 vs sl_pct.
    """
    min_dist_pct = sl_pct * 1.5    # minimum R:R = 2.0

    if direction == "bull":
        candidates = []

        # 1. Equal Highs (strongest BSL) – optimized O(n log n)
        highs = df["high"].values[-100:]
        sorted_highs = np.sort(highs)
        clusters = []
        current_cluster = [sorted_highs[0]]
        for h in sorted_highs[1:]:
            if abs(h - current_cluster[-1]) / max(h, 1e-10) < 0.002:
                current_cluster.append(h)
            else:
                if len(current_cluster) >= 2:
                    clusters.append(max(current_cluster))
                current_cluster = [h]
        if len(current_cluster) >= 2:
            clusters.append(max(current_cluster))
        for hi in clusters:
            if hi > price * 1.001:
                candidates.append({"level": float(hi), "type": "Equal Highs (BSL)", "strength": 3})

        # 2. Swing Highs not yet swept
        for idx, val in structure.get("swing_highs", []):
            if val > price * (1 + min_dist_pct / 100):
                candidates.append({"level": val, "type": "Swing High (BSL)", "strength": 2})

        # 3. Unmitigated Bear OB bottoms above price
        for ob in bear_obs:
            if ob["ob_bottom"] > price * (1 + min_dist_pct / 100):
                candidates.append({"level": ob["ob_bottom"], "type": "Supply Zone (BSL)", "strength": 2})

        # 4. Previous structure high
        prev_high = structure.get("prev_high")
        if prev_high and prev_high > price * (1 + min_dist_pct / 100):
            candidates.append({"level": prev_high, "type": "Structure High", "strength": 1})

        valid = [c for c in candidates if c["level"] > price * (1 + min_dist_pct / 100)]
        if not valid:
            return None, "No bull liquidity found"

        best = min(valid, key=lambda x: x["level"])
        return float(best["level"]), best["type"]

    else:  # bear direction — SSL
        candidates = []

        # 1. Equal Lows – optimized
        lows = df["low"].values[-100:]
        sorted_lows = np.sort(lows)
        clusters = []
        current_cluster = [sorted_lows[0]]
        for l in sorted_lows[1:]:
            if abs(l - current_cluster[-1]) / max(l, 1e-10) < 0.002:
                current_cluster.append(l)
            else:
                if len(current_cluster) >= 2:
                    clusters.append(min(current_cluster))
                current_cluster = [l]
        if len(current_cluster) >= 2:
            clusters.append(min(current_cluster))
        for lo in clusters:
            if lo < price * 0.999:
                candidates.append({"level": float(lo), "type": "Equal Lows (SSL)", "strength": 3})

        # 2. Swing Lows not yet swept
        for idx, val in structure.get("swing_lows", []):
            if val < price * (1 - min_dist_pct / 100):
                candidates.append({"level": val, "type": "Swing Low (SSL)", "strength": 2})

        # 3. Unmitigated Bull OB tops below price
        for ob in bull_obs:
            if ob["ob_top"] < price * (1 - min_dist_pct / 100):
                candidates.append({"level": ob["ob_top"], "type": "Demand Zone (SSL)", "strength": 2})

        # 4. Previous structure low
        prev_low = structure.get("prev_low")
        if prev_low and prev_low < price * (1 - min_dist_pct / 100):
            candidates.append({"level": prev_low, "type": "Structure Low", "strength": 1})

        valid = [c for c in candidates if c["level"] < price * (1 - min_dist_pct / 100)]
        if not valid:
            return None, "No bear liquidity found"

        best = max(valid, key=lambda x: x["level"])
        return float(best["level"]), best["type"]


def find_second_liquidity(price: float, direction: str, tp1: float,
                           df: pd.DataFrame,
                           bull_obs: list, bear_obs: list,
                           structure: dict):
    """Find TP2 — next liquidity pool beyond TP1."""
    if tp1 is None:
        return None, ""

    if direction == "bull":
        candidates = []
        for idx, val in structure.get("swing_highs", []):
            if val > tp1 * 1.005:
                candidates.append(val)
        for ob in bear_obs:
            if ob["ob_bottom"] > tp1 * 1.005:
                candidates.append(ob["ob_bottom"])
        # Equal highs beyond TP1 (simplified O(n) pass)
        highs = df["high"].values[-150:]
        high_above = sorted([h for h in highs if h > tp1 * 1.005])
        if len(high_above) >= 2:
            clusters = []
            current = [high_above[0]]
            for h in high_above[1:]:
                if abs(h - current[-1]) / max(h, 1e-10) < 0.002:
                    current.append(h)
                else:
                    if len(current) >= 2:
                        clusters.append(max(current))
                    current = [h]
            if len(current) >= 2:
                clusters.append(max(current))
            for cl in clusters:
                candidates.append(cl)
        return (float(min(candidates)), "Swing High / Equal Highs") if candidates else (None, "")

    else:  # bear
        candidates = []
        for idx, val in structure.get("swing_lows", []):
            if val < tp1 * 0.995:
                candidates.append(val)
        for ob in bull_obs:
            if ob["ob_top"] < tp1 * 0.995:
                candidates.append(ob["ob_top"])
        lows_below = sorted([l for l in df["low"].values[-150:] if l < tp1 * 0.995], reverse=True)
        if len(lows_below) >= 2:
            clusters = []
            current = [lows_below[0]]
            for l in lows_below[1:]:
                if abs(l - current[-1]) / max(l, 1e-10) < 0.002:
                    current.append(l)
                else:
                    if len(current) >= 2:
                        clusters.append(min(current))
                    current = [l]
            if len(current) >= 2:
                clusters.append(min(current))
            for cl in clusters:
                candidates.append(cl)
        return (float(max(candidates)), "Swing Low / Equal Lows") if candidates else (None, "")

# ══════════════════════════════════════════════════════════════════════════════
# WALLET SAFETY VALIDATOR — V10 New
# ══════════════════════════════════════════════════════════════════════════════
def validate_wallet_safety(trade: dict, open_trades: int = 0) -> dict:
    """
    Before accepting any trade, validate all wallet safety conditions.
    Bug 6 Fix: liquidation_pct = 4.5%, not 5%.
    """
    issues = []

    if trade["sl_pct"] > WALLET_CONFIG["max_sl_pct"]:
        issues.append(f"SL {trade['sl_pct']:.2f}% exceeds {WALLET_CONFIG['max_sl_pct']}% hard cap")

    liq_buffer = WALLET_CONFIG["liquidation_pct"] - trade["sl_pct"]
    if liq_buffer < 1.0:
        issues.append(f"Liquidation buffer only {liq_buffer:.2f}% — too close")

    if open_trades >= WALLET_CONFIG["max_concurrent"]:
        issues.append(f"Max {WALLET_CONFIG['max_concurrent']} concurrent trades reached")

    if trade["rr"] < WALLET_CONFIG.get("min_rr", 2.0):
        issues.append(f"R:R {trade['rr']:.2f} below minimum 2.0")

    if issues:
        return {"valid": False, "issues": issues, "liq_buffer": liq_buffer}

    pos = WALLET_CONFIG["position_size"]
    tp1 = trade.get("tp1", trade.get("entry", 0))
    entry = trade.get("entry", 0)
    profit_pct = abs(tp1 - entry) / max(entry, 1e-10)
    # Adjust profits for fees
    gross_tp1_profit = pos * profit_pct
    fee_cost = pos * TOTAL_FEE_PCT
    net_tp1_profit = round(gross_tp1_profit - fee_cost, 2)
    # TP2: if exists, calculate similarly (approx)
    tp2 = trade.get("tp2")
    if tp2 and isinstance(tp2, float):
        gross_tp2_profit = pos * abs(tp2 - entry) / max(entry, 1e-10)
        net_tp2_profit = round(gross_tp2_profit - fee_cost, 2)
    else:
        net_tp2_profit = 0

    return {
        "valid":               True,
        "max_loss_usd":        trade["max_loss_usd"],
        "tp1_profit_usd":      net_tp1_profit,
        "tp2_profit_usd":      net_tp2_profit,
        "safety_buffer_pct":   liq_buffer,
        "issues":              [],
    }

# ══════════════════════════════════════════════════════════════════════════════
# BUILD TRADE HELPER
# ══════════════════════════════════════════════════════════════════════════════
def build_trade(tier: str, direction: str, price: float,
                sl: float, sl_pct: float, tp: float, rr: float,
                ob: dict, tp_type: str = "", ob_inside: bool = False) -> dict:
    """Build standardized trade dict with wallet info."""
    safety_buffer = WALLET_CONFIG["liquidation_pct"] - sl_pct
    pos           = WALLET_CONFIG["position_size"]
    fee_cost = pos * TOTAL_FEE_PCT
    gross_tp1 = pos * abs(tp - price) / max(price, 1e-10)
    net_tp1 = round(gross_tp1 - fee_cost, 2)

    return {
        "signal":               direction,
        "tier":                 tier,
        "entry":                round(price, 8),
        "sl":                   round(sl, 8),
        "sl_pct":               round(sl_pct, 3),
        "tp1":                  round(tp, 8),
        "tp2":                  None,
        "tp2_type":             "",
        "tp1_type":             tp_type,
        "rr":                   round(rr, 2),
        "ob":                   ob,
        "ob_inside":            ob_inside,
        "margin":               WALLET_CONFIG["margin_per_trade"],
        "position":             pos,
        "max_loss_usd":         round(pos * sl_pct / 100, 2),
        "tp1_profit_usd":       net_tp1,
        "liquidation_distance": round(safety_buffer, 2),
        "wallet_safe":          safety_buffer > 1.0,
        "reason":               f"{tier} | SL {sl_pct:.2f}% | R:R {rr:.2f}",
    }

# ══════════════════════════════════════════════════════════════════════════════
# TIERED TRADE FINDER — V10 Core (replaces generate_signal_v9)
# Bug C Fix: Tier 2 distance absolute, corrected.
# HTF Gate added (Fix F).
# ══════════════════════════════════════════════════════════════════════════════
def find_best_trade(price: float, bull_obs: list, bear_obs: list,
                    structure: dict, htf_bias: str,
                    df: pd.DataFrame, bos_type: str, regime: str) -> dict:
    """
    Try each tier from tightest SL to loosest.
    Return first tier that gives R:R >= 2.0.
    HOLD only if no tier qualifies.
    """
    if regime == "VOLATILE":
        log.warning("⚡ VOLATILE market — HOLD forced")
        return {
            "signal": "HOLD", "tier": "HOLD",
            "entry": price, "sl": price * 0.98,
            "sl_pct": 2.0, "tp1": None, "tp2": None,
            "tp1_type": "", "tp2_type": "",
            "rr": 0.0, "ob": None, "ob_inside": False,
            "margin": WALLET_CONFIG["margin_per_trade"],
            "position": WALLET_CONFIG["position_size"],
            "max_loss_usd": 0, "tp1_profit_usd": 0,
            "liquidation_distance": WALLET_CONFIG["liquidation_pct"],
            "wallet_safe": True,
            "reason": "VOLATILE market — trading paused",
        }

    # ── TIER 1: Price INSIDE OB ──────────────────────────────────────────────
    for ob in bull_obs:
        if ob["ob_bottom"] <= price <= ob["ob_top"]:
            if htf_bias == "BEAR":          # HTF Gate
                continue
            sl     = price * (1 - 0.004)           # Bug 1 Fix: fixed 0.4%
            sl_pct = (price - sl) / price * 100    # = 0.4% guaranteed

            if sl_pct <= 0.5:
                tp, tp_type = find_nearest_liquidity(
                    price, "bull", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (tp - price) / max(price - sl, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥇 TIER 1 BUY — inside demand zone | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_1", "BUY", price, sl, sl_pct, tp, rr, ob, tp_type, ob_inside=True)

    for ob in bear_obs:
        if ob["ob_bottom"] <= price <= ob["ob_top"]:
            if htf_bias == "BULL":
                continue
            sl     = price * (1 + 0.004)
            sl_pct = (sl - price) / price * 100

            if sl_pct <= 0.5:
                tp, tp_type = find_nearest_liquidity(
                    price, "bear", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (price - tp) / max(sl - price, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥇 TIER 1 SELL — inside supply zone | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_1", "SELL", price, sl, sl_pct, tp, rr, ob, tp_type, ob_inside=True)

    # ── TIER 2: Price Approaching OB (within 0.5% of OB top) ─────────────────
    for ob in bull_obs:
        # Bug C Fix: absolute distance from ob_top
        dist_pct = abs(price - ob["ob_top"]) / max(price, 1e-10) * 100
        if dist_pct <= 0.5 and price >= ob["ob_top"]:  # price at or above ob_top
            if htf_bias == "BEAR":
                continue
            sl     = ob["ob_bottom"] * 0.998
            sl_pct = (price - sl) / max(price, 1e-10) * 100

            if sl_pct <= 1.0:
                tp, tp_type = find_nearest_liquidity(
                    price, "bull", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (tp - price) / max(price - sl, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥈 TIER 2 BUY — approaching demand | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_2", "BUY", price, sl, sl_pct, tp, rr, ob, tp_type)

    for ob in bear_obs:
        # For bearish OB, check distance from ob_bottom (or ob_top, using absolute)
        # Using ob_bottom as the reference for approach (price above bottom for sell)
        dist_pct = abs(price - ob["ob_bottom"]) / max(price, 1e-10) * 100
        if dist_pct <= 0.5 and price <= ob["ob_bottom"]:
            if htf_bias == "BULL":
                continue
            sl     = ob["ob_top"] * 1.002
            sl_pct = (sl - price) / max(price, 1e-10) * 100

            if sl_pct <= 1.0:
                tp, tp_type = find_nearest_liquidity(
                    price, "bear", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (price - tp) / max(sl - price, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥈 TIER 2 SELL — approaching supply | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_2", "SELL", price, sl, sl_pct, tp, rr, ob, tp_type)

    # ── TIER 3: BOS + Structure Confirmed ────────────────────────────────────
    if (bos_type == "BOS_UP" and htf_bias == "BULL"
            and structure["type"] in ("UPTREND", "BREAKOUT")):
        last_low = structure.get("last_low") or structure.get("prev_low")
        if last_low is not None:
            sl     = last_low * 0.998
            sl_pct = (price - sl) / max(price, 1e-10) * 100

            if 0 < sl_pct <= 1.5:
                tp, tp_type = find_nearest_liquidity(
                    price, "bull", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (tp - price) / max(price - sl, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥉 TIER 3 BUY — BOS+structure | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_3", "BUY", price, sl, sl_pct, tp, rr, None, tp_type)

    if (bos_type == "BOS_DOWN" and htf_bias == "BEAR"
            and structure["type"] in ("DOWNTREND", "BREAKDOWN")):
        last_high = structure.get("last_high") or structure.get("prev_high")
        if last_high is not None:
            sl     = last_high * 1.002
            sl_pct = (sl - price) / max(price, 1e-10) * 100

            if 0 < sl_pct <= 1.5:
                tp, tp_type = find_nearest_liquidity(
                    price, "bear", df, bull_obs, bear_obs, structure, sl_pct)
                if tp is not None:
                    rr = (price - tp) / max(sl - price, 1e-10)
                    if rr >= 2.0:
                        log.success(f"🥉 TIER 3 SELL — BOS+structure | SL {sl_pct:.2f}% | R:R {rr:.2f}")
                        return build_trade("TIER_3", "SELL", price, sl, sl_pct, tp, rr, None, tp_type)

    # ── WORST CASE: 2% hard cap SL — only when liquidity crystal clear ──────
    if htf_bias in ("BULL", "BEAR"):
        direction  = "bull" if htf_bias == "BULL" else "bear"
        sig_label  = "BUY"  if htf_bias == "BULL" else "SELL"
        sl_pct_wc  = 2.0
        sl_wc = price * (1 - 0.02) if direction == "bull" else price * (1 + 0.02)

        tp, tp_type = find_nearest_liquidity(
            price, direction, df, bull_obs, bear_obs, structure, sl_pct_wc)
        if tp is not None:
            rr = abs(tp - price) / max(abs(sl_wc - price), 1e-10)
            if rr >= 2.0:
                log.warning(f"⚠️ WORST CASE {sig_label} — 2% SL | R:R {rr:.2f}")
                return build_trade("WORST_CASE", sig_label, price,
                                   sl_wc, sl_pct_wc, tp, rr, None, tp_type)

    # ── HOLD ───────────────────────────────────────────────────────────────────
    log.info("⏸ HOLD — no valid setup in any tier")
    return {
        "signal": "HOLD", "tier": "HOLD",
        "entry": price, "sl": price * 0.98, "sl_pct": 2.0,
        "tp1": None, "tp2": None, "tp1_type": "", "tp2_type": "",
        "rr": 0.0, "ob": None, "ob_inside": False,
        "margin": WALLET_CONFIG["margin_per_trade"],
        "position": WALLET_CONFIG["position_size"],
        "max_loss_usd": 0, "tp1_profit_usd": 0,
        "liquidation_distance": WALLET_CONFIG["liquidation_pct"],
        "wallet_safe": True,
        "reason": "No valid setup found in any tier (Tier1→2→3→WorstCase all failed)",
    }

# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURE ANALYSIS (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
def analyze_structure(df, lookback=75):
    if len(df) < lookback + 7:
        return _empty_struct("UNKNOWN", 0, "Insufficient data")
    rec = df.tail(lookback).reset_index(drop=True)
    hi, lo, cl = rec["high"].values, rec["low"].values, rec["close"].values
    s_highs, s_lows = [], []
    for i in range(3, len(rec) - 3):
        lh, rh = hi[i-3:i], hi[i+1:i+4]
        ll, rl = lo[i-3:i], lo[i+1:i+4]
        if len(lh) < 3 or len(rh) < 3:
            continue
        if hi[i] >= max(lh) and hi[i] >= max(rh):
            base = max(float(min(lo[max(0,i-5):i])), 1e-10)
            if (hi[i] - base) / base >= cfg["STRUCT_MIN_SWING"]:
                s_highs.append((i, float(hi[i])))
        if lo[i] <= min(ll) and lo[i] <= min(rl):
            base = max(float(lo[i]), 1e-10)
            if (max(hi[max(0,i-5):i]) - lo[i]) / base >= cfg["STRUCT_MIN_SWING"]:
                s_lows.append((i, float(lo[i])))

    if len(s_highs) < 2 or len(s_lows) < 2:
        return _empty_struct("RANGING", 35, "Insufficient swings")

    last_h = s_highs[-3:] if len(s_highs) >= 3 else s_highs
    last_l = s_lows[-3:]  if len(s_lows)  >= 3 else s_lows
    hh = all(last_h[i][1] > last_h[i-1][1] for i in range(1, len(last_h)))
    hl = all(last_l[i][1] > last_l[i-1][1] for i in range(1, len(last_l)))
    lh = all(last_h[i][1] < last_h[i-1][1] for i in range(1, len(last_h)))
    ll_flag = all(last_l[i][1] < last_l[i-1][1] for i in range(1, len(last_l)))

    last_close = float(cl[-1])
    prev_high  = s_highs[-2][1] if len(s_highs) >= 2 else float(hi[-1])
    prev_low   = s_lows[-2][1]  if len(s_lows)  >= 2 else float(lo[-1])
    breakout   = last_close > prev_high * 1.003
    breakdown  = last_close < prev_low  * 0.997

    if hh and hl:        stype, conf = "UPTREND",   90 if breakout  else 78
    elif lh and ll_flag: stype, conf = "DOWNTREND", 90 if breakdown else 78
    elif breakout:       stype, conf = "BREAKOUT",  72
    elif breakdown:      stype, conf = "BREAKDOWN", 72
    else:                stype, conf = "RANGING",   45

    return {
        "type": stype, "confidence": conf,
        "swing_highs": s_highs, "swing_lows": s_lows,
        "last_high": s_highs[-1][1] if s_highs else None,
        "last_low":  s_lows[-1][1]  if s_lows  else None,
        "prev_high": prev_high, "prev_low": prev_low,
        "breakout": breakout, "breakdown": breakdown,
        "hh": hh, "hl": hl, "lh": lh, "ll": ll_flag,
    }

def _empty_struct(stype, conf, note):
    return {
        "type": stype, "confidence": conf,
        "swing_highs": [], "swing_lows": [],
        "last_high": None, "last_low": None,
        "prev_high": None, "prev_low": None,
        "breakout": False, "breakdown": False,
        "hh": False, "hl": False, "lh": False, "ll": False,
        "note": note,
    }

# ══════════════════════════════════════════════════════════════════════════════
# WHALE TRACKER (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def fetch_order_book(symbol: str):
    for name, ex in ex_pool.items():
        try:
            ob = ex.fetch_order_book(symbol, limit=cfg["OB_DEPTH"])
            if ob and ob.get("bids") and ob.get("asks"):
                log.info(f"📖 OB: {name.upper()}")
                return ob
        except Exception:
            continue
    return None

def analyze_ob(symbol, price):
    ob = fetch_order_book(symbol)
    if not ob:
        return _empty_ob()
    bids = np.array(ob["bids"][:cfg["OB_DEPTH"]], dtype=float)
    asks = np.array(ob["asks"][:cfg["OB_DEPTH"]], dtype=float)
    if bids.size == 0 or asks.size == 0:
        return _empty_ob()
    bid_usdt = float(np.sum(bids[:,0] * bids[:,1]))
    ask_usdt = float(np.sum(asks[:,0] * asks[:,1]))
    imbal    = bid_usdt / max(bid_usdt + ask_usdt, 1e-10)
    avg_b    = float(np.mean(bids[:,1]))
    avg_a    = float(np.mean(asks[:,1]))
    b_walls  = [(float(bids[i,0]), float(bids[i,1]))
                for i in range(len(bids)) if bids[i,1] >= avg_b * cfg["WALL_MULT"]]
    a_walls  = [(float(asks[i,0]), float(asks[i,1]))
                for i in range(len(asks)) if asks[i,1] >= avg_a * cfg["WALL_MULT"]]
    if   imbal >= 0.65: sig, note = "BULL",      f"Heavy bid {imbal:.1%}"
    elif imbal <= 0.35: sig, note = "BEAR",      f"Heavy ask {1-imbal:.1%}"
    elif imbal >= 0.55: sig, note = "MILD_BULL", f"Mild bid {imbal:.1%}"
    elif imbal <= 0.45: sig, note = "MILD_BEAR", f"Mild ask {1-imbal:.1%}"
    else:               sig, note = "NEUTRAL",   f"Balanced {imbal:.1%}"
    return {
        "imbalance": round(imbal, 4), "bid_usdt": round(bid_usdt, 2),
        "ask_usdt": round(ask_usdt, 2), "bid_walls": b_walls,
        "ask_walls": a_walls, "ob_signal": sig, "ob_note": note,
        "available": True,
    }

def _empty_ob():
    return {
        "imbalance": 0.5, "bid_usdt": 0, "ask_usdt": 0,
        "bid_walls": [], "ask_walls": [],
        "ob_signal": "NEUTRAL", "ob_note": "OB unavailable", "available": False,
    }

def detect_whales(df):
    if len(df) < 20:
        return _empty_whale()
    ma20  = df["volume"].rolling(20).mean().bfill()
    candles = []
    for i in range(max(0, len(df)-50), len(df)):
        vm = float(ma20.iloc[i])
        if vm == 0 or pd.isna(vm):
            continue
        vr   = df["volume"].iloc[i] / vm
        op   = max(float(df["open"].iloc[i]), 1e-10)
        pmov = abs(float(df["close"].iloc[i]) - op) / op
        if vr >= cfg["WHALE_VOL_THRESH"] and pmov >= cfg["WHALE_MOVE_MIN"]:
            bull = float(df["close"].iloc[i]) >= op
            candles.append({
                "idx": i, "ts": df["timestamp"].iloc[i],
                "price": float(df["close"].iloc[i]),
                "vol_ratio": round(vr, 2),
                "price_move_pct": round(pmov*100, 3),
                "direction": "BUY" if bull else "SELL",
                "type": "ACCUM" if bull else "DISTRIB",
            })
    rec      = df.tail(30)
    bull_vol = float(rec.loc[rec["close"]>=rec["open"], "volume"].sum())
    bear_vol = float(rec.loc[rec["close"]<rec["open"],  "volume"].sum())
    cvd_r    = bull_vol / max(bull_vol + bear_vol, 1e-10)
    cvd_t    = ("BULL" if cvd_r >= 0.60 else "BEAR" if cvd_r <= 0.40 else "NEUTRAL")
    return {
        "whale_candles": candles, "recent": candles[-1] if candles else None,
        "cvd_ratio": round(cvd_r, 4), "cvd_trend": cvd_t, "total": len(candles),
    }

def _empty_whale():
    return {
        "whale_candles": [], "recent": None,
        "cvd_ratio": 0.5, "cvd_trend": "NEUTRAL", "total": 0,
    }

def whale_score(ob_data, wc, signal):
    pts, notes = 0.0, []
    is_bull = "BUY" in signal
    if ob_data.get("available"):
        s = ob_data["ob_signal"]
        pts += {"BULL":4,"MILD_BULL":2,"NEUTRAL":1}.get(s,0) if is_bull else \
               {"BEAR":4,"MILD_BEAR":2,"NEUTRAL":1}.get(s,0)
        notes.append(f"OB: {ob_data['ob_note']}")
        if is_bull and ob_data["bid_walls"]:
            pts += 1; notes.append(f"Bid wall ({len(ob_data['bid_walls'])} lvl)")
        elif not is_bull and ob_data["ask_walls"]:
            pts += 1; notes.append(f"Ask wall ({len(ob_data['ask_walls'])} lvl)")
    else:
        notes.append("OB unavailable")
    cvd, cvd_r = wc["cvd_trend"], wc["cvd_ratio"]
    if (is_bull and cvd=="BULL") or (not is_bull and cvd=="BEAR"):
        pts += 3; notes.append(f"CVD aligned ({cvd_r:.1%})")
    elif cvd == "NEUTRAL":
        pts += 1; notes.append("CVD neutral")
    else:
        notes.append("CVD opposing")
    rw = wc.get("recent")
    if rw:
        match = (is_bull and rw["direction"]=="BUY") or (not is_bull and rw["direction"]=="SELL")
        if match:
            pts += 2; notes.append(f"Whale {rw['type']} {rw['vol_ratio']}x")
        else:
            notes.append(f"Whale opposing {rw['type']}")
    else:
        notes.append("No whale candle")
    score = round(min(10.0, pts), 1)
    label = ("🐋 CONFIRMED" if score>=7.5 else "🐟 PARTIAL" if score>=5.0
             else "🔍 NEUTRAL" if score>=3.0 else "🚨 OPPOSING")
    return score, label, notes

# ══════════════════════════════════════════════════════════════════════════════
# PATTERN DETECTION (unchanged from V9)
# ══════════════════════════════════════════════════════════════════════════════
def detect_patterns(df):
    if len(df) < 5:
        return {}
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values,  df["close"].values)
    avg = np.mean([abs(c[x]-o[x]) for x in range(-10, 0)]) or 1e-10
    i, j, k = -1, -2, -3

    def body(x): return abs(c[x]-o[x])
    def rng(x):  return max(h[x]-l[x], 1e-10)
    def bull(x): return c[x] > o[x]
    def uw(x):   return h[x] - max(c[x], o[x])
    def lw(x):   return min(c[x], o[x]) - l[x]

    return {
        "bull_engulf": (not bull(j) and bull(i) and c[i]>o[j] and o[i]<c[j] and body(i)>body(j)*1.1),
        "bear_engulf": (bull(j) and not bull(i) and c[i]<o[j] and o[i]>c[j] and body(i)>body(j)*1.1),
        "hammer":      (lw(i)>=body(i)*2 and uw(i)<=body(i)*0.3 and body(i)>0 and rng(i)>avg*0.5),
        "shoot_star":  (uw(i)>=body(i)*2 and lw(i)<=body(i)*0.3 and body(i)>0 and rng(i)>avg*0.5),
        "doji":        (body(i)<=rng(i)*0.1 and rng(i)>avg*0.3),
        "morn_star":   (len(df)>=5 and not bull(k) and body(k)>avg*0.8
                        and body(j)<avg*0.3 and bull(i) and c[i]>(o[k]+c[k])/2),
        "eve_star":    (len(df)>=5 and bull(k) and body(k)>avg*0.8
                        and body(j)<avg*0.3 and not bull(i) and c[i]<(o[k]+c[k])/2),
    }

def detect_divergences(df, lookback=30):
    if len(df) < lookback:
        return False, False
    rec   = df.tail(lookback).reset_index(drop=True)
    price = rec["close"].values
    rsi   = rec["RSI"].values
    obv   = rec["OBV"].values
    sw    = max(3, lookback//5)

    def swings(arr, w):
        hi, lo = [], []
        for i in range(w, len(arr)-w):
            s = arr[i-w:i+w+1]
            if arr[i] >= np.max(s) - 1e-10: hi.append(i)
            if arr[i] <= np.min(s) + 1e-10: lo.append(i)
        return hi, lo

    ph, pl = swings(price, sw)
    bull_div = bear_div = False
    if len(pl) >= 2:
        p1, p2 = pl[-2], pl[-1]
        if price[p2] < price[p1]*0.999 and rsi[p2] > rsi[p1]+1.5:
            bull_div = True
    if len(ph) >= 2:
        p1, p2 = ph[-2], ph[-1]
        if price[p2] > price[p1]*1.001 and rsi[p2] < rsi[p1]-1.5:
            bear_div = True
    half = lookback // 2
    pt = price[-1] - price[-half] if half < len(price) else 0
    ot = obv[-1]   - obv[-half]   if half < len(obv)   else 0
    if pt < -price[-1]*0.005 and ot > 0: bull_div = True
    elif pt > price[-1]*0.005 and ot < 0: bear_div = True
    return bull_div, bear_div

def get_htf_bias(df4h):
    if df4h is None or len(df4h) < 10:
        return "NEUTRAL", "HTF unavailable"
    last  = df4h.iloc[-1]
    price = float(last["close"])
    checks = [
        price > float(last["EMA9"]),
        price > float(last["EMA50"]),
        price > float(last["EMA200"]),
        float(last["MACD"]) > float(last["MACD_Sig"]),
        float(last["RSI"]) > 55,
        int(last["ST_Dir"]) == 1,
        float(last["ADX_Pos"]) > float(last["ADX_Neg"]),
    ]
    bull = sum(checks); tot = len(checks)
    if bull >= int(tot*0.7):          return "BULL",    f"4H Bullish ({bull}/{tot})"
    elif (tot-bull) >= int(tot*0.7):  return "BEAR",    f"4H Bearish ({tot-bull}/{tot})"
    else:                             return "NEUTRAL",  f"4H Neutral (B:{bull} Br:{tot-bull})"

def classify_regime(df):
    last  = df.iloc[-1]
    adx   = float(last["ADX"])
    adxp  = float(last["ADX_Pos"])
    adxn  = float(last["ADX_Neg"])
    price = float(last["close"])
    e9, e50, e200 = float(last["EMA9"]), float(last["EMA50"]), float(last["EMA200"])
    bbw   = float(last["BB_Width"])
    atp   = float(last["ATR_Pct"])
    q80   = float(df["BB_Width"].quantile(0.80))
    q40   = float(df["BB_Width"].quantile(0.40))
    pb    = price > e9 > e50 > e200
    nb    = price < e9 < e50 < e200
    if atp > 85 and bbw > q80:                   return "VOLATILE",     "⚡ Very high volatility"
    if adx >= 35 and adxp > adxn and pb:         return "STRONG_BULL",  "🚀 Very strong uptrend"
    if adx >= 35 and adxn > adxp and nb:         return "STRONG_BEAR",  "💀 Very strong downtrend"
    if adx > 22 and adxp > adxn and price>e9>e50: return "TRENDING_UP", "📈 Uptrend"
    if adx > 22 and adxn > adxp and price<e9<e50: return "TRENDING_DOWN","📉 Downtrend"
    if adx < 20 and bbw < q40:                   return "RANGING",      "↔ Sideways"
    return "NORMAL", "🔄 Normal"

# ══════════════════════════════════════════════════════════════════════════════
# ML SYSTEM — Bug E Fix: walk-forward MAE computed in price terms
# ══════════════════════════════════════════════════════════════════════════════
FEATURE_COLS = [
    "close","RSI","MACD","MACD_Hist","ATR","OBV",
    "EMA9","EMA21","BB_Width","BB_Pos","Vol_Ratio","ADX",
    "Stoch_K","ST_Dir","Body_Ratio","Upper_Wick","Lower_Wick",
    "Price_vs_VWAP","EMA_Spread","Momentum_5","Momentum_20",
    "CCI","WilliamsR","ROC","CVD20","Vol_Pct",
]

def _clean_Xy(X, y):
    X = np.where(np.isinf(X), np.nan, X)
    y = np.where(np.isinf(y), np.nan, y)
    col_medians = np.nanmedian(X, axis=0)
    nan_mask_X  = np.isnan(X)
    inds = np.where(nan_mask_X)
    X[inds] = np.take(col_medians, inds[1])
    valid = ~np.isnan(y)
    X, y  = X[valid], y[valid]
    std   = X.std(axis=0, keepdims=True).clip(min=1e-8)
    X     = np.clip(X, -10 * std, 10 * std)
    return X, y

def _apply_scaler_and_flatten(X_3d, feat_scaler, y_scaler, y_raw):
    n, seq_len, n_feats = X_3d.shape
    flat_2d   = X_3d.reshape(-1, n_feats)
    scaled_2d = feat_scaler.transform(flat_2d)
    scaled_2d = np.nan_to_num(scaled_2d, nan=0.0, posinf=0.0, neginf=0.0)
    scaled_3d = scaled_2d.reshape(n, seq_len, n_feats)
    flat  = scaled_3d.reshape(n, -1)
    stats = np.concatenate([
        scaled_3d.mean(axis=1),
        scaled_3d.std(axis=1),
        scaled_3d[:, -1, :] - scaled_3d[:, max(0, seq_len - 5):, :].mean(axis=1),
    ], axis=1)
    X_2d = np.concatenate([flat, stats], axis=1)
    y_scaled = y_scaler.transform(y_raw.reshape(-1, 1)).ravel()
    return X_2d, y_scaled

def build_features(df, seq_len=60):
    feats   = [c for c in FEATURE_COLS if c in df.columns]
    log.info(f"🧠 Features ({len(feats)}): {', '.join(feats[:8])}…")
    raw     = df[feats].copy().ffill().bfill().fillna(0).replace([np.inf, -np.inf], 0)
    raw_vals = raw.values.astype(float)
    X_windows, y_list = [], []
    for i in range(seq_len, len(raw_vals)):
        X_windows.append(raw_vals[i - seq_len : i])
        y_list.append(raw_vals[i, 0])
    X_arr = np.array(X_windows, dtype=float)
    y_arr = np.array(y_list,    dtype=float)
    log.info(f"Raw sequences: {X_arr.shape}, samples: {len(y_arr)}")
    return X_arr, y_arr, feats

def walk_forward_validate(X_raw, y_raw, n_splits=5):
    n, seq_len, n_feats = X_raw.shape
    fold_size = n // (n_splits + 1)
    price_errors = []  # store absolute error in original price units
    for i in range(1, n_splits + 1):
        train_end = fold_size * i
        val_start = train_end
        val_end   = min(val_start + fold_size, n)
        if val_end <= val_start or train_end < 10:
            continue
        X_tr_raw  = X_raw[:train_end]
        X_val_raw = X_raw[val_start:val_end]
        y_tr_raw  = y_raw[:train_end]
        y_val_raw = y_raw[val_start:val_end]
        fold_feat_scaler = RobustScaler()
        fold_feat_scaler.fit(X_tr_raw.reshape(-1, n_feats))
        fold_y_scaler = RobustScaler()
        fold_y_scaler.fit(y_tr_raw.reshape(-1, 1))
        X_tr,  y_tr  = _apply_scaler_and_flatten(X_tr_raw,  fold_feat_scaler, fold_y_scaler, y_tr_raw)
        X_val, y_val = _apply_scaler_and_flatten(X_val_raw, fold_feat_scaler, fold_y_scaler, y_val_raw)
        X_tr,  y_tr  = _clean_Xy(X_tr.copy(),  y_tr.copy())
        X_val, y_val = _clean_Xy(X_val.copy(), y_val.copy())
        if len(X_tr) < 10 or len(X_val) < 2:
            continue
        try:
            m = Ridge(alpha=1.0)
            m.fit(X_tr, y_tr)
            pred_scaled = m.predict(X_val)
            # Inverse transform to get price predictions and actuals
            pred_price = fold_y_scaler.inverse_transform(pred_scaled.reshape(-1,1)).ravel()
            actual_price = fold_y_scaler.inverse_transform(y_val.reshape(-1,1)).ravel()
            mae_price = np.mean(np.abs(pred_price - actual_price))
            price_errors.append(mae_price)
        except Exception as e:
            log.warning(f"WF fold {i} failed: {e}")
    if price_errors:
        wf_mae_price = float(np.mean(price_errors))
        # Return price-based MAE
        return wf_mae_price
    return 0.0

def build_ensemble(X_raw, y_raw):
    n, seq_len, n_feats = X_raw.shape
    split = int(n * 0.80)
    X_tr_raw  = X_raw[:split]
    X_val_raw = X_raw[split:]
    y_tr_raw  = y_raw[:split]
    y_val_raw = y_raw[split:]
    feat_scaler = RobustScaler()
    feat_scaler.fit(X_tr_raw.reshape(-1, n_feats))
    y_scaler = RobustScaler()
    y_scaler.fit(y_tr_raw.reshape(-1, 1))
    X_tr,  y_tr  = _apply_scaler_and_flatten(X_tr_raw,  feat_scaler, y_scaler, y_tr_raw)
    X_val, y_val = _apply_scaler_and_flatten(X_val_raw, feat_scaler, y_scaler, y_val_raw)
    X_tr,  y_tr  = _clean_Xy(X_tr.copy(),  y_tr.copy())
    X_val, y_val = _clean_Xy(X_val.copy(), y_val.copy())
    models = {
        "Ridge": Ridge(alpha=0.5),
        "GBM":   GradientBoostingRegressor(n_estimators=80, max_depth=4,
                     learning_rate=0.05, subsample=0.8, random_state=42),
        "RF":    RandomForestRegressor(n_estimators=60, max_depth=6,
                     min_samples_leaf=5, random_state=42, n_jobs=1),
    }
    if HAS_XGB:
        models["XGB"] = XGBRegressor(n_estimators=80, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=0, n_jobs=1)
    if HAS_LGB:
        models["LGB"] = LGBMRegressor(n_estimators=80, max_depth=4, learning_rate=0.05,
            subsample=0.8, random_state=42, verbose=-1, n_jobs=1)
    trained, weights, val_maes = {}, {}, {}
    for name, m in models.items():
        try:
            m.fit(X_tr, y_tr)
            pred = m.predict(X_val)
            mae  = mean_absolute_error(y_val, pred)
            val_maes[name] = mae
            weights[name]  = 1.0 / max(mae, 1e-8)
            trained[name]  = m
            log.success(f"  {name}: MAE={mae:.5f}")
        except Exception as e:
            log.warning(f"  {name} failed: {e}")
    total_w = sum(weights.values())
    norm_w  = {k: v / total_w for k, v in weights.items()}
    wf_mae_price = walk_forward_validate(X_raw, y_raw)
    log.info(f"Walk-forward MAE (price): {wf_mae_price:.5f}")
    return trained, norm_w, val_maes, wf_mae_price, feat_scaler, y_scaler

def ensemble_predict(trained, weights, X_raw, feat_scaler, y_scaler, feats):
    X_last = X_raw[-1:]
    n, seq_len, n_feats = X_last.shape
    scaled_2d = feat_scaler.transform(X_last.reshape(-1, n_feats))
    scaled_2d = np.nan_to_num(scaled_2d, nan=0.0, posinf=0.0, neginf=0.0)
    scaled_3d = scaled_2d.reshape(1, seq_len, n_feats)
    flat  = scaled_3d.reshape(1, -1)
    stats = np.concatenate([
        scaled_3d.mean(axis=1),
        scaled_3d.std(axis=1),
        scaled_3d[:, -1, :] - scaled_3d[:, max(0, seq_len - 5):, :].mean(axis=1),
    ], axis=1)
    X_inp = np.nan_to_num(np.concatenate([flat, stats], axis=1), nan=0.0, posinf=0.0, neginf=0.0)
    pred_scaled = sum(weights.get(name, 0) * float(m.predict(X_inp)[0])
                      for name, m in trained.items())
    return float(y_scaler.inverse_transform([[pred_scaled]])[0][0])

# ══════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS — V10 Unified Flow
# Bug 3 Fix: Single flow, find_best_trade() is the ONLY signal source
# ══════════════════════════════════════════════════════════════════════════════
def run_analysis_v10():
    log.clear()
    result = {}

    try:
        log.info(f"📡 Fetching {cfg['COIN']} [{cfg['TF']}]")
        df = fetch_ohlcv(cfg["COIN"], cfg["TF"])
        df = add_indicators(df)

        log.info(f"📡 Fetching HTF [{cfg['HTF']}]")
        try:
            df_htf  = fetch_ohlcv(cfg["COIN"], cfg["HTF"])
            df_htf  = add_indicators(df_htf)
            htf_bias, htf_desc = get_htf_bias(df_htf)
        except Exception as e:
            log.warning(f"HTF failed: {e}")
            df_htf = None; htf_bias = "NEUTRAL"; htf_desc = "Unavailable"

        price = float(df["close"].iloc[-1])

        # Step 1: Context analysis
        patterns           = detect_patterns(df)
        bull_div, bear_div = detect_divergences(df)
        structure          = analyze_structure(df, cfg["STRUCT_LOOKBACK"])
        regime, regime_desc = classify_regime(df)

        # Step 2: OB Detection (V10 Bug 4 fix inside)
        log.info("📦 Detecting Order Blocks (V10: 3-candle mitigation)...")
        bull_obs, bear_obs = detect_order_blocks(df)
        bos_type, bos_desc = detect_bos(df, structure)

        # Step 3: ML Prediction (context only — not primary signal)
        pred_price = price
        wf_mae_pct = 0.0
        adx_val    = float(df["ADX"].iloc[-1])

        if adx_val >= 20:
            log.info("🧠 Building ensemble model...")
            X_raw, y_raw, feats = build_features(df, cfg["SEQ_LEN"])
            if len(X_raw) >= 50:
                trained, weights, val_maes, wf_mae_price, feat_scaler, y_scaler = \
                    build_ensemble(X_raw, y_raw)
                pred_price = ensemble_predict(
                    trained, weights, X_raw, feat_scaler, y_scaler, feats)
                # Bug E Fix: wf_mae_price is already in price units
                wf_mae_pct = abs(wf_mae_price / max(price, 1e-10)) * 100
                log.success(
                    f"Prediction: {pred_price:.6f} "
                    f"({(pred_price-price)/price*100:+.2f}%) | "
                    f"WF Error: {wf_mae_pct:.3f}%")
        else:
            log.info(f"Model gated — ADX={adx_val:.1f} < 20")

        # Step 4: Find Best Trade (MAIN SIGNAL — replaces generate_signal_v9)
        trade = find_best_trade(
            price, bull_obs, bear_obs,
            structure, htf_bias, df, bos_type, regime
        )

        # Step 5: Add TP2 if trade found
        if trade["signal"] != "HOLD":
            direction = "bull" if "BUY" in trade["signal"] else "bear"
            tp1 = trade["tp1"]
            tp2, tp2_type = find_second_liquidity(
                price, direction, tp1, df, bull_obs, bear_obs, structure)
            trade["tp2"]      = tp2
            trade["tp2_type"] = tp2_type

        # Step 6: Wallet safety check
        open_trades = st.session_state.get("open_trades", 0)
        safety = validate_wallet_safety(trade, open_trades)
        if not safety["valid"] and trade["signal"] != "HOLD":
            log.warning(f"⚠️ Wallet safety FAIL: {' | '.join(safety['issues'])}")
            trade["signal"] = "HOLD"
            trade["reason"] = " | ".join(safety["issues"])
            safety = validate_wallet_safety(trade, open_trades)

        # Step 7: Whale + OB confirmation (context, not gate)
        ob_res = analyze_ob(cfg["COIN"], price)
        wc_res = detect_whales(df)
        ws, wl, wn = whale_score(ob_res, wc_res, trade["signal"])

        result = {
            **trade,
            "price":      price,
            "pred_price": pred_price,
            "chg_pct":    (pred_price - price) / max(price, 1e-10) * 100,
            "wf_mae_pct": wf_mae_pct,
            "structure":  structure,
            "htf_bias":   htf_bias,
            "htf_desc":   htf_desc,
            "bull_obs":   bull_obs,
            "bear_obs":   bear_obs,
            "bos_type":   bos_type,
            "bos_desc":   bos_desc,
            "patterns":   patterns,
            "bull_div":   bull_div,
            "bear_div":   bear_div,
            "regime":     regime,
            "regime_desc": regime_desc,
            "whale_score": ws,
            "whale_label": wl,
            "whale_notes": wn,
            "safety":     safety,
            "ob":         ob_res,
            "wc":         wc_res,
            "df":         df,
            "df_htf":     df_htf,
        }
        log.success("✅ V10 Analysis complete")

    except Exception as e:
        import traceback
        log.error(f"CRITICAL: {e}")
        result = {"error": str(e), "trace": traceback.format_exc()}

    return result

# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI — 4 TAB LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
st.title("🐋 Crypto Bot V10  ·  Tiered SL + Liquidity TP")
st.caption(
    f"ICT OB · Demand/Supply Zones · BOS · Liquidity-Based TP · "
    f"$100 Wallet · 20x Leverage  |  "
    f"Logged in as **{st.session_state.get('current_user','')}**")

run_btn = st.sidebar.button("🚀 Run Analysis", use_container_width=True)

# ── Open Trades Tracker ────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("📊 Open Trades")
open_trades_count = st.sidebar.number_input(
    "Currently Open Trades", 0, 2, 0, 1,
    help="Track how many trades are open (max 2)")
st.session_state["open_trades"] = open_trades_count
margin_used = open_trades_count * WALLET_CONFIG["margin_per_trade"]
margin_pct  = margin_used / WALLET_CONFIG["total_balance"] * 100
if margin_used > 0:
    st.sidebar.progress(int(margin_pct), f"${margin_used}/{WALLET_CONFIG['total_balance']} margin used")

if run_btn:
    with st.spinner("Analysing… (30–60 sec on first run)"):
        res = run_analysis_v10()

    if "error" in res:
        st.error(res["error"])
        st.code(res.get("trace",""))
        st.stop()

    # ── TABS ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Signal", "📦 Order Blocks", "💼 Wallet", "🏗 Market"
    ])

    # ════════════════════════════════════════════════════════════════════
    # TAB 1 — SIGNAL
    # ════════════════════════════════════════════════════════════════════
    with tab1:
        with st.expander("📋 Execution Logs", expanded=False):
            st.text(log.text())

        sig   = res["signal"]
        tier  = res["tier"]
        tc    = TIER_COLORS.get(tier, TIER_COLORS["HOLD"])

        sig_class = ("signal-buy" if "BUY" in sig else
                     "signal-sell" if "SELL" in sig else "signal-hold")

        # Signal Banner
        tier_labels = {
            "TIER_1": "🥇 TIER 1 — OB Inside",
            "TIER_2": "🥈 TIER 2 — OB Approach",
            "TIER_3": "🥉 TIER 3 — BOS+Structure",
            "WORST_CASE": "⚠️ WORST CASE — 2% SL",
            "HOLD":  "⏸ HOLD",
        }
        tier_label = tier_labels.get(tier, tier)

        st.markdown(
            f'<div style="background:{tc["bg"]};border:2px solid {tc["border"]};'
            f'border-radius:10px;padding:16px 20px;margin-bottom:12px;">'
            f'<span class="{sig_class}">{sig}</span>'
            f'<span style="color:{tc["text"]};font-size:1rem;font-weight:bold;'
            f'margin-left:16px;background:#21262d;padding:4px 12px;'
            f'border-radius:8px;">{tier_label}</span>'
            f'</div>',
            unsafe_allow_html=True)
        st.caption(res.get("reason",""))

        # ── Tier Pyramid ─────────────────────────────────────────────────
        st.subheader("🏆 Tier System")
        tier_cols = st.columns(5)
        all_tiers = ["TIER_1","TIER_2","TIER_3","WORST_CASE","HOLD"]
        tier_short = ["🥇 T1","🥈 T2","🥉 T3","⚠️ WC","⏸ HOLD"]
        for idx, (t, label) in enumerate(zip(all_tiers, tier_short)):
            c = TIER_COLORS[t]
            active = tier == t
            border_w = "3px" if active else "1px"
            opacity = "1.0" if active else "0.4"
            tier_cols[idx].markdown(
                f'<div style="background:{c["bg"]};border:{border_w} solid {c["border"]};'
                f'border-radius:8px;padding:8px;text-align:center;opacity:{opacity};">'
                f'<span style="color:{c["text"]};font-weight:bold;font-size:0.85rem;">{label}</span>'
                f'</div>',
                unsafe_allow_html=True)

        st.markdown("---")

        # ── Key Metrics ──────────────────────────────────────────────────
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Entry",      f"{res['entry']:.6f}")
        sl_label = f"SL ({res.get('sl_pct', 0):.2f}%)"
        c2.metric(sl_label,     f"{res['sl']:.6f}")
        tp1_val = res.get("tp1") or "N/A"
        tp2_val = res.get("tp2") or "N/A"
        tp1_str = f"{tp1_val:.6f}" if isinstance(tp1_val, float) else "N/A"
        tp2_str = f"{tp2_val:.6f}" if isinstance(tp2_val, float) else "N/A"
        c3.metric(f"TP1 ({res.get('tp1_type','')[:12]})", tp1_str)
        c4.metric(f"TP2 ({res.get('tp2_type','')[:12]})", tp2_str)
        c5.metric("R:R",          f"1:{res['rr']:.2f}")
        c6.metric("Prediction",   f"{res['pred_price']:.5f}",
                  f"{res['chg_pct']:+.2f}%")

        if res.get("wf_mae_pct", 0) > 0:
            st.caption(f"🧠 ML Walk-forward error: {res['wf_mae_pct']:.3f}% of price")

        st.markdown("---")

        # ── Mini Price Chart ─────────────────────────────────────────────
        df_plot = res.get("df")
        if df_plot is not None:
            st.subheader("📈 Price Chart  (🟢 Demand Zone · 🔴 SL Zone · 🎯 Liquidity TP)")
            tail = df_plot.tail(200).reset_index(drop=True)
            ts   = tail["timestamp"]
            n_c  = len(tail)

            fig, ax = plt.subplots(figsize=(14, 6))
            fig.patch.set_facecolor("#010409")
            ax.set_facecolor("#0d1117")

            ax.plot(ts, tail["close"], color="#58a6ff", lw=1.5, label="Close", zorder=3)
            ax.plot(ts, tail["EMA9"],  color="#f0883e", ls="--", lw=1, label="EMA9",  zorder=2)
            ax.plot(ts, tail["EMA50"], color="#bc8cff", ls="-.", lw=1, label="EMA50", zorder=2)

            x_start_ts = ts.iloc[max(0, n_c - cfg["OB_LOOKBACK"])]
            x_end_ts   = ts.iloc[-1]

            # Demand zones (green)
            for ob in res["bull_obs"]:
                ax.axhspan(ob["ob_bottom"], ob["ob_top"],
                           alpha=0.18, color="#2ea043", zorder=1)
                ax.hlines([ob["ob_top"], ob["ob_bottom"]],
                          xmin=x_start_ts, xmax=x_end_ts,
                          colors="#2ea043", lw=0.8, ls="--", zorder=2)
                ax.text(ts.iloc[-1], ob["ob_top"],
                        f" 🟢 Demand {ob['ob_top']:.4f}",
                        color="#2ea043", fontsize=7, va="bottom", zorder=5)
                # SL zone (red) below demand
                ax.axhspan(ob["sl_level"], ob["ob_bottom"],
                           alpha=0.20, color="#f85149", zorder=1)
                ax.text(ts.iloc[-1], ob["sl_level"],
                        f" 🔴 SL {ob['sl_level']:.4f}",
                        color="#f85149", fontsize=7, va="top", zorder=5)

            # Supply zones (red)
            for ob in res["bear_obs"]:
                ax.axhspan(ob["ob_bottom"], ob["ob_top"],
                           alpha=0.18, color="#f85149", zorder=1)
                ax.hlines([ob["ob_top"], ob["ob_bottom"]],
                          xmin=x_start_ts, xmax=x_end_ts,
                          colors="#f85149", lw=0.8, ls="--", zorder=2)
                ax.text(ts.iloc[-1], ob["ob_top"],
                        f" 🔴 Supply {ob['ob_top']:.4f}",
                        color="#f85149", fontsize=7, va="bottom", zorder=5)

            # Entry / SL / TP lines
            ax.axhline(res["entry"], color="white",   ls=":",  lw=1.2,
                       label=f"Entry {res['entry']:.4f}", zorder=4)
            ax.axhline(res["sl"],    color="#f85149", ls="--", lw=1.5,
                       label=f"SL {res['sl']:.4f}", zorder=4)
            if isinstance(res.get("tp1"), float):
                ax.axhline(res["tp1"], color="#2ea043", ls="--", lw=1.5,
                           label=f"TP1 {res['tp1']:.4f}", zorder=4)
            if isinstance(res.get("tp2"), float):
                ax.axhline(res["tp2"], color="#56d364", ls=":", lw=1,
                           label=f"TP2 {res['tp2']:.4f}", zorder=4)

            # Swing dots
            s = res["structure"]
            for idx, val in s.get("swing_highs",[])[-5:]:
                idx_c = min(idx, n_c - 1)
                ax.scatter(ts.iloc[idx_c], val, color="#f85149", s=30, zorder=6)
            for idx, val in s.get("swing_lows",[])[-5:]:
                idx_c = min(idx, n_c - 1)
                ax.scatter(ts.iloc[idx_c], val, color="#2ea043", s=30, zorder=6)

            # BOS label
            if res["bos_type"] != "NONE":
                bos_clr = "#2ea043" if res["bos_type"]=="BOS_UP" else "#f85149"
                ax.text(ts.iloc[int(n_c*0.02)],
                        float(tail["close"].max()) * 0.9993,
                        f"  {res['bos_desc']}",
                        color=bos_clr, fontsize=9, fontweight="bold", zorder=7)

            legend_patches = [
                mpatches.Patch(color="#2ea043", alpha=0.5, label="Demand Zone"),
                mpatches.Patch(color="#f85149", alpha=0.5, label="SL / Supply Zone"),
            ]
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(handles=handles + legend_patches, fontsize=7,
                      loc="upper left", facecolor="#0d1117", labelcolor="white")
            ax.tick_params(colors="#8b949e")
            for spine in ax.spines.values(): spine.set_color("#30363d")
            ax.grid(True, alpha=0.12)
            plt.xticks(rotation=20)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

    # ════════════════════════════════════════════════════════════════════
    # TAB 2 — ORDER BLOCKS
    # ════════════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("📦 Order Block Analysis  (ICT / SMC Strategy)")

        ob_c1, ob_c2, ob_c3 = st.columns(3)
        with ob_c1:
            bos_icon = "🔼" if res["bos_type"]=="BOS_UP" else \
                       "🔽" if res["bos_type"]=="BOS_DOWN" else "⏸"
            st.metric("Break of Structure", f"{bos_icon} {res['bos_type']}", res["bos_desc"])
        with ob_c2:
            ob_side = "—"
            if res.get("tier") in ("TIER_1","TIER_2") and res.get("ob_inside"):
                ob_side = "BULL" if "BUY" in res["signal"] else "BEAR"
            st.metric("Active Tier", res["tier"], f"OB Inside: {ob_side}")
        with ob_c3:
            tob = res.get("ob") or {}
            st.metric("Order Book Signal",
                      tob.get("ob_signal","N/A"),
                      tob.get("ob_note",""))

        st.markdown("---")

        # ── Liquidity Path Visualization ─────────────────────────────────
        st.subheader("🎯 Liquidity Path  (Entry → TP1 → TP2)")
        liq_c1, liq_c2, liq_c3, liq_c4, liq_c5 = st.columns([2,1,2,1,2])
        with liq_c1:
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #21262d;'
                f'border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="color:#8b949e;font-size:0.8rem;">ENTRY</div>'
                f'<div style="color:#58a6ff;font-weight:bold;font-size:1.1rem;">'
                f'{res["entry"]:.6f}</div>'
                f'<div style="color:#8b949e;font-size:0.75rem;">Current Price</div>'
                f'</div>', unsafe_allow_html=True)
        with liq_c2:
            st.markdown('<div style="text-align:center;padding-top:20px;'
                        'font-size:1.5rem;color:#58a6ff;">→</div>', unsafe_allow_html=True)
        with liq_c3:
            tp1_disp = f"{res['tp1']:.6f}" if isinstance(res.get("tp1"), float) else "—"
            tp1_type = res.get("tp1_type","")
            pnl1 = res.get("tp1_profit_usd", 0)
            tp1_color = "#2ea043" if "BUY" in res["signal"] else "#f85149"
            st.markdown(
                f'<div style="background:#0d2818;border:1px solid #2ea043;'
                f'border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="color:#8b949e;font-size:0.8rem;">TP1 — {tp1_type[:20]}</div>'
                f'<div style="color:{tp1_color};font-weight:bold;font-size:1.1rem;">'
                f'{tp1_disp}</div>'
                f'<div style="color:#56d364;font-size:0.75rem;">+${pnl1:.2f} net profit</div>'
                f'</div>', unsafe_allow_html=True)
        with liq_c4:
            st.markdown('<div style="text-align:center;padding-top:20px;'
                        'font-size:1.5rem;color:#58a6ff;">→</div>', unsafe_allow_html=True)
        with liq_c5:
            tp2_disp = f"{res['tp2']:.6f}" if isinstance(res.get("tp2"), float) else "—"
            tp2_type = res.get("tp2_type","")
            safety_data = res.get("safety", {})
            tp2_profit = safety_data.get("tp2_profit_usd", 0)
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #56d364;'
                f'border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="color:#8b949e;font-size:0.8rem;">TP2 — {tp2_type[:20]}</div>'
                f'<div style="color:#56d364;font-weight:bold;font-size:1.1rem;">'
                f'{tp2_disp}</div>'
                f'<div style="color:#56d364;font-size:0.75rem;">+${tp2_profit:.2f} net profit</div>'
                f'</div>', unsafe_allow_html=True)

        st.markdown("---")

        # ── Demand Zones Table ─────────────────────────────────────────
        with st.expander(f"🟢 Bullish Demand Zones ({len(res['bull_obs'])})", expanded=True):
            if res["bull_obs"]:
                rows = []
                for ob in reversed(res["bull_obs"]):
                    rows.append({
                        "Zone Bottom": f"{ob['ob_bottom']:.8f}",
                        "Zone Top":    f"{ob['ob_top']:.8f}",
                        "SL Level":    f"{ob['sl_level']:.8f}",
                        "Impulse %":   f"{ob['impulse_pct']}%",
                        "Vol Ratio":   f"{ob['vol_ratio']}x",
                        "Status":      "🟢 Active (V10: 3-candle check)",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("No bullish demand zones found")

        with st.expander(f"🔴 Bearish Supply Zones ({len(res['bear_obs'])})", expanded=True):
            if res["bear_obs"]:
                rows = []
                for ob in reversed(res["bear_obs"]):
                    rows.append({
                        "Zone Bottom": f"{ob['ob_bottom']:.8f}",
                        "Zone Top":    f"{ob['ob_top']:.8f}",
                        "SL Level":    f"{ob['sl_level']:.8f}",
                        "Impulse %":   f"{ob['impulse_pct']}%",
                        "Vol Ratio":   f"{ob['vol_ratio']}x",
                        "Status":      "🔴 Active (V10: 3-candle check)",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("No bearish supply zones found")

    # ════════════════════════════════════════════════════════════════════
    # TAB 3 — WALLET
    # ════════════════════════════════════════════════════════════════════
    with tab3:
        st.subheader("💼 Wallet & Position Management")

        w1, w2, w3, w4, w5 = st.columns(5)
        w1.metric("Total Wallet",   f"${WALLET_CONFIG['total_balance']}")
        w2.metric("Margin/Trade",   f"${WALLET_CONFIG['margin_per_trade']}")
        w3.metric("Leverage",       f"{WALLET_CONFIG['leverage']}x")
        w4.metric("Position Size",  f"${WALLET_CONFIG['position_size']}")
        w5.metric("Liquidation",    f"{WALLET_CONFIG['liquidation_pct']}%",
                  "away from entry")

        st.markdown("---")

        # Margin Used Bar
        st.subheader("📊 Margin Utilization")
        total_margin_available = WALLET_CONFIG["total_balance"]
        margin_used_now = open_trades_count * WALLET_CONFIG["margin_per_trade"]
        if res["signal"] != "HOLD":
            margin_used_now += WALLET_CONFIG["margin_per_trade"]
        margin_pct_now = min(100, int(margin_used_now / total_margin_available * 100))
        color = "#2ea043" if margin_pct_now < 50 else "#f0883e" if margin_pct_now < 80 else "#f85149"
        st.markdown(
            f'<div style="background:#21262d;border-radius:6px;height:24px;margin:4px 0;">'
            f'<div style="background:{color};width:{margin_pct_now}%;height:100%;'
            f'border-radius:6px;"></div></div>'
            f'<div style="color:#8b949e;font-size:0.85rem;">'
            f'${margin_used_now} / ${total_margin_available} ({margin_pct_now}%) margin used</div>',
            unsafe_allow_html=True)

        st.markdown("---")

        # Safety Analysis
        st.subheader("🛡 Safety Analysis  (SL vs Liquidation)")
        sl_pct_trade = res.get("sl_pct", 2.0)
        liq_pct      = WALLET_CONFIG["liquidation_pct"]
        buffer_pct   = liq_pct - sl_pct_trade

        sa1, sa2, sa3 = st.columns(3)
        sa1.metric("Our SL Distance",      f"{sl_pct_trade:.2f}%",
                   "from entry")
        sa2.metric("Liquidation Distance", f"{liq_pct:.1f}%",
                   "from entry (actual)")
        buf_color = "🟢 Safe" if buffer_pct >= 2.0 else "🟡 OK" if buffer_pct >= 1.0 else "🔴 Danger"
        sa3.metric("Safety Buffer",        f"{buffer_pct:.2f}%", buf_color)

        st.markdown("---")

        # Scenario Table (adjusted for fees)
        st.subheader("📋 Trade Scenario Analysis  ($200 position)")
        pos_size = WALLET_CONFIG["position_size"]
        price_e  = res.get("entry", 1)
        tp1_val  = res.get("tp1", price_e)
        tp2_val  = res.get("tp2", price_e)
        sl_val   = res.get("sl",  price_e)
        fee_cost = pos_size * TOTAL_FEE_PCT

        sl_loss  = round(pos_size * sl_pct_trade / 100, 2)
        tp1_gain = round(pos_size * abs((tp1_val or price_e) - price_e) / max(price_e, 1e-10) - fee_cost, 2) if isinstance(tp1_val, float) else 0
        tp2_gain = round(pos_size * abs((tp2_val or price_e) - price_e) / max(price_e, 1e-10) - fee_cost, 2) if isinstance(tp2_val, float) else 0
        five_sl  = round(sl_loss * 5, 2)
        bal_after_5sl = WALLET_CONFIG["total_balance"] - five_sl

        scenarios = pd.DataFrame([
            {"Scenario": "✅ TP1 Hit",         "P&L USD": f"+${tp1_gain}", "Wallet After": f"${WALLET_CONFIG['total_balance'] + tp1_gain}"},
            {"Scenario": "🎯 TP2 Hit",         "P&L USD": f"+${tp2_gain}", "Wallet After": f"${WALLET_CONFIG['total_balance'] + tp2_gain}"},
            {"Scenario": "❌ SL Hit (1x)",     "P&L USD": f"-${sl_loss}",  "Wallet After": f"${WALLET_CONFIG['total_balance'] - sl_loss}"},
            {"Scenario": "💥 5 SL in a Row",   "P&L USD": f"-${five_sl}", "Wallet After": f"${bal_after_5sl} ({'✅ Alive' if bal_after_5sl > 0 else '❌ Blown'})"},
            {"Scenario": "🔄 Break Even",      "P&L USD": "$0.00",         "Wallet After": f"${WALLET_CONFIG['total_balance']}"},
        ])
        st.dataframe(scenarios, use_container_width=True)

        safety_data = res.get("safety", {})
        if not safety_data.get("valid", True):
            st.error("⚠️ Safety Issues: " + " | ".join(safety_data.get("issues",[])))
        else:
            st.success(f"✅ Trade is within wallet safety parameters  |  Buffer: {buffer_pct:.2f}%  |  Max Loss: ${sl_loss}")

    # ════════════════════════════════════════════════════════════════════
    # TAB 4 — MARKET
    # ════════════════════════════════════════════════════════════════════
    with tab4:
        st.subheader("🏗 Market Context")

        mkt_c1, mkt_c2 = st.columns(2)
        with mkt_c1:
            st.subheader("📐 Market Structure")
            s = res["structure"]
            struct_color = ("#2ea043" if s["type"] in ("UPTREND","BREAKOUT") else
                            "#f85149" if s["type"] in ("DOWNTREND","BREAKDOWN") else
                            "#8b949e")
            st.markdown(
                f'<div style="background:#0d1117;border-left:4px solid {struct_color};'
                f'padding:12px;border-radius:6px;margin-bottom:8px;">'
                f'<div style="color:{struct_color};font-weight:bold;font-size:1.1rem;">'
                f'{s["type"]}</div>'
                f'<div style="color:#8b949e;font-size:0.85rem;">Confidence: {s["confidence"]}%</div>'
                f'</div>', unsafe_allow_html=True)
            if s.get("hh") and s.get("hl"): st.success("📈 HH + HL confirmed (uptrend)")
            elif s.get("lh") and s.get("ll"): st.error("📉 LH + LL confirmed (downtrend)")
            else: st.info(f"↔ Mixed structure")
            st.caption(res.get("regime_desc",""))

        with mkt_c2:
            st.subheader("📡 4H Higher Timeframe Bias")
            bias = res["htf_bias"]
            bias_color = "#2ea043" if bias=="BULL" else "#f85149" if bias=="BEAR" else "#8b949e"
            bias_icon  = "🟢" if bias=="BULL" else "🔴" if bias=="BEAR" else "⚪"
            st.markdown(
                f'<div style="background:#0d1117;border-left:4px solid {bias_color};'
                f'padding:12px;border-radius:6px;margin-bottom:8px;">'
                f'<div style="color:{bias_color};font-weight:bold;font-size:1.1rem;">'
                f'{bias_icon} {bias}</div>'
                f'<div style="color:#8b949e;font-size:0.85rem;">{res["htf_desc"]}</div>'
                f'</div>', unsafe_allow_html=True)

        st.markdown("---")

        # Whale
        whal_c1, whal_c2 = st.columns(2)
        with whal_c1:
            st.subheader("🐋 Whale Activity")
            ws = res.get("whale_score", 0)
            wl = res.get("whale_label","—")
            whale_color = "#2ea043" if ws >= 7 else "#f0883e" if ws >= 4 else "#f85149"
            st.markdown(
                f'<div style="background:#0d1117;border-left:4px solid {whale_color};'
                f'padding:12px;border-radius:6px;">'
                f'<div style="color:{whale_color};font-weight:bold;">{wl}</div>'
                f'<div style="color:#8b949e;font-size:0.85rem;">Score: {ws}/10</div>'
                f'</div>', unsafe_allow_html=True)
            for note in res.get("whale_notes", []):
                st.caption(note)

            wc = res.get("wc",{})
            if wc.get("total", 0) > 0:
                st.caption(f"Whale candles detected: {wc['total']} | CVD: {wc['cvd_trend']} ({wc['cvd_ratio']:.1%})")

        with whal_c2:
            st.subheader("🕯 Candlestick Patterns")
            found = [k for k, v in res.get("patterns", {}).items() if v]
            if found:
                for p in found:
                    is_bull_pat = p in ("bull_engulf","hammer","morn_star")
                    if is_bull_pat: st.success(p.replace("_"," ").title())
                    else: st.error(p.replace("_"," ").title())
            else:
                st.info("No strong candlestick pattern")
            if res.get("bull_div"): st.success("🔺 Bullish RSI/OBV Divergence")
            if res.get("bear_div"): st.error("🔻 Bearish RSI/OBV Divergence")

        st.markdown("---")

        # BOS Detail
        st.subheader("🔼 Break of Structure")
        bos_c1, bos_c2 = st.columns(2)
        with bos_c1:
            bos_color = "#2ea043" if res["bos_type"]=="BOS_UP" else \
                        "#f85149" if res["bos_type"]=="BOS_DOWN" else "#8b949e"
            st.markdown(
                f'<div style="background:#0d1117;border-left:4px solid {bos_color};'
                f'padding:12px;border-radius:6px;">'
                f'<div style="color:{bos_color};font-weight:bold;">{res["bos_type"]}</div>'
                f'<div style="color:#8b949e;font-size:0.85rem;">{res["bos_desc"]}</div>'
                f'</div>', unsafe_allow_html=True)
        with bos_c2:
            s = res["structure"]
            prev_h = s.get("prev_high")
            prev_l = s.get("prev_low")
            if prev_h:
                st.caption(f"Previous High: {prev_h:.6f}")
            if prev_l:
                st.caption(f"Previous Low:  {prev_l:.6f}")

else:
    # ── Landing Page ───────────────────────────────────────────────────
    st.info("👈 Configure settings in sidebar, then click **🚀 Run Analysis**.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
### 🆕 What's New in V10

**🎯 Tiered SL System (4 tiers)**
- 🥇 **Tier 1** (SL ≤ 0.5%) — Price inside OB
- 🥈 **Tier 2** (SL ≤ 1.0%) — Approaching OB
- 🥉 **Tier 3** (SL ≤ 1.5%) — BOS + Structure
- ⚠️ **Worst Case** (SL = 2.0%) — Fallback

**📦 Liquidity-Based TP (Not ATR)**
- Equal Highs → BSL (Buy Side Liquidity)
- Swing Highs not swept → BSL
- Unmitigated OB tops → BSL
- Mirror logic for SSL (bear side)
        """)

    with col_b:
        st.markdown("""
### 🐛 8 Bugs Fixed from V9

| # | Bug | Fix |
|---|-----|-----|
| 1 | Tier 1 SL math wrong | Fixed 0.4% from price |
| 2 | Liquidity scope crash | All params passed explicitly |
| 3 | Signal+tier disconnect | Single unified flow |
| 4 | OB mitigation too easy | 3 consecutive closes |
| 5 | None crash on structure | Null-check added |
| 6 | Liquidation % wrong | 4.5% actual (not 5%) |
| 7 | TP no R:R check | R:R gate inside TP fn |
| 8 | ATR-based TP | Liquidity pool TP |
        """)

    st.info("👈 Configure settings in sidebar, then click **🚀 Run Analysis**.")
