import logging
import time
import sys
from datetime import datetime

from config import SYMBOL, GRANULARITY, CANDLE_HISTORY, DERIV_API_TOKEN
from deriv_client import DerivClient
from strategy import SMCStrategy
from risk_manager import DailyLossGuard

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Candle normalizer (Deriv returns strings, we need floats)
# ──────────────────────────────────────────────────────────────

def normalize_candle(raw: dict) -> dict:
    return {
        "epoch": int(raw.get("epoch", 0)),
        "open" : float(raw["open"]),
        "high" : float(raw["high"]),
        "low"  : float(raw["low"]),
        "close": float(raw["close"]),
    }


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("  SMC Forex Bot — Starting")
    logger.info(f"  Symbol      : {SYMBOL}")
    logger.info(f"  Timeframe   : M{GRANULARITY // 60}")
    logger.info(f"  Started at  : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    # ── Validate config ───────────────────────────────────────
    if not DERIV_API_TOKEN or DERIV_API_TOKEN == "your_token_here":
        logger.critical("DERIV_API_TOKEN is not set. Add it to Railway environment variables.")
        sys.exit(1)

    # ── Connect to Deriv ──────────────────────────────────────
    client = DerivClient()
    client.connect()

    if not client.wait_authorized(timeout=20):
        logger.critical("Authorization failed. Check your API token.")
        sys.exit(1)

    # ── Balance & Loss Guard ──────────────────────────────────
    balance = client.get_balance()
    logger.info(f"Starting balance: {balance} {client.account_currency}")
    loss_guard = DailyLossGuard(starting_balance=balance)

    # ── Load historical candles ───────────────────────────────
    logger.info(f"Loading {CANDLE_HISTORY} historical candles…")
    raw_candles = client.get_candles(SYMBOL, GRANULARITY, count=CANDLE_HISTORY)
    if not raw_candles:
        logger.critical("Failed to load historical candles. Exiting.")
        sys.exit(1)

    strategy = SMCStrategy(client=client, loss_guard=loss_guard)
    strategy.candles = [normalize_candle(c) for c in raw_candles]
    logger.info(f"Loaded {len(strategy.candles)} candles. Bot is live.")

    # ── Live candle handler ───────────────────────────────────
    last_epoch = strategy.candles[-1]["epoch"]

    def on_ohlc(data):
        nonlocal last_epoch
        ohlc = data.get("ohlc", {})
        if not ohlc:
            return

        candle = {
            "epoch": int(ohlc.get("open_time", 0)),
            "open" : float(ohlc["open"]),
            "high" : float(ohlc["high"]),
            "low"  : float(ohlc["low"]),
            "close": float(ohlc["close"]),
        }

        # Only process each candle once (when it closes)
        if candle["epoch"] <= last_epoch:
            return

        last_epoch = candle["epoch"]
        ts = datetime.utcfromtimestamp(candle["epoch"]).strftime("%H:%M")
        logger.info(
            f"[{ts}] O:{candle['open']} H:{candle['high']} "
            f"L:{candle['low']} C:{candle['close']}"
        )

        try:
            strategy.on_candle(candle)
        except Exception as e:
            logger.exception(f"Strategy error on candle: {e}")

    # ── Subscribe to live feed ────────────────────────────────
    client.subscribe_candles(SYMBOL, GRANULARITY, on_ohlc)

    # ── Keep alive ────────────────────────────────────────────
    logger.info("Bot running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            # Refresh balance every minute
            client.get_balance()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
