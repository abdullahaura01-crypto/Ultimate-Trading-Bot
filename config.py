import os
from dotenv import load_dotenv

load_dotenv()

# --- Deriv API ---
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN")
DERIV_APP_ID   = os.getenv("DERIV_APP_ID", "1089")  # Read from Railway env var

# --- Trading Pair ---
SYMBOL      = os.getenv("SYMBOL", "frxEURUSD")   # EUR/USD on Deriv
GRANULARITY = 900                                  # M15 = 900 seconds

# --- Position Sizing ---
STAKE      = float(os.getenv("STAKE", 10))        # USD per trade
MULTIPLIER = int(os.getenv("MULTIPLIER", 10))     # 10x leverage
RISK_PCT   = float(os.getenv("RISK_PCT", 0.02))   # 2% of balance per trade
MAX_OPEN_TRADES = 2                               # max simultaneous positions (entry1 + pyramid)

# --- Strategy Parameters ---
MIN_RR_RATIO     = 2.6     # Minimum risk:reward to take trade
ZONE_TOLERANCE   = 0.0008  # 0.08% price tolerance for zone matching (~8 pips on EURUSD)
SWING_LOOKBACK   = 5       # Candles each side to confirm a swing high/low
ZONE_MIN_TOUCHES = 2       # Minimum touches to qualify as a valid zone (double bottom)
CANDLE_HISTORY   = 150     # Candles to load for analysis
SWEEP_BUFFER     = 0.0002  # Price must close this % above/below zone after sweep

# --- Candle Pattern Thresholds ---
HAMMER_WICK_RATIO = 2.0    # Lower wick must be 2x the body size
MAX_UPPER_WICK    = 0.4    # Upper wick max 40% of body (hammer filter)

# --- Pyramid (Entry 2) ---
PYRAMID_ENABLED       = True
STRUCTURE_BREAK_PIPS  = 0.0010   # Pips price must break structure by to trigger pyramid

# --- Risk Guard ---
MAX_DAILY_LOSS_PCT = 0.06   # Stop trading if daily loss exceeds 6% of balance
