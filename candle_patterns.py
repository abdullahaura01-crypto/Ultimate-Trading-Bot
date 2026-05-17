import logging
from config import HAMMER_WICK_RATIO, MAX_UPPER_WICK

logger = logging.getLogger(__name__)


def _body(c: dict) -> float:
    return abs(c["close"] - c["open"])


def _lower_wick(c: dict) -> float:
    return min(c["open"], c["close"]) - c["low"]


def _upper_wick(c: dict) -> float:
    return c["high"] - max(c["open"], c["close"])


def is_bullish(c: dict) -> bool:
    return c["close"] >= c["open"]


def is_bearish(c: dict) -> bool:
    return c["close"] < c["open"]


# ──────────────────────────────────────────────────────────────
# Reversal Confirmation Patterns (Long)
# ──────────────────────────────────────────────────────────────

def is_hammer(c: dict) -> bool:
    """
    Hammer (bullish reversal):
    - Long lower wick >= HAMMER_WICK_RATIO × body
    - Small or no upper wick
    - Candle must be bullish (green) for higher quality
    """
    body = _body(c)
    if body == 0:
        return False   # doji — skip for cleaner signals
    lower = _lower_wick(c)
    upper = _upper_wick(c)
    return (
        lower >= body * HAMMER_WICK_RATIO
        and upper <= body * MAX_UPPER_WICK
        and is_bullish(c)
    )


def is_bullish_engulfing(c: dict, prev: dict) -> bool:
    """
    Bullish engulfing:
    - Previous candle is bearish (red)
    - Current candle is bullish (green) and body fully engulfs previous body
    """
    return (
        is_bearish(prev)
        and is_bullish(c)
        and c["open"]  < prev["close"]
        and c["close"] > prev["open"]
    )


def is_long_confirmation(candle: dict, prev_candle: dict | None = None) -> bool:
    """
    Returns True if candle is a valid long confirmation signal.
    Accepts hammer OR bullish engulfing (if prev candle provided).
    """
    if is_hammer(candle):
        logger.debug("Pattern: Hammer detected")
        return True
    if prev_candle and is_bullish_engulfing(candle, prev_candle):
        logger.debug("Pattern: Bullish engulfing detected")
        return True
    return False


# ──────────────────────────────────────────────────────────────
# Reversal Confirmation Patterns (Short)
# ──────────────────────────────────────────────────────────────

def is_shooting_star(c: dict) -> bool:
    """
    Shooting star (bearish reversal):
    - Long upper wick >= HAMMER_WICK_RATIO × body
    - Small or no lower wick
    - Candle must be bearish (red)
    """
    body = _body(c)
    if body == 0:
        return False
    upper = _upper_wick(c)
    lower = _lower_wick(c)
    return (
        upper >= body * HAMMER_WICK_RATIO
        and lower <= body * MAX_UPPER_WICK
        and is_bearish(c)
    )


def is_bearish_engulfing(c: dict, prev: dict) -> bool:
    """
    Bearish engulfing:
    - Previous candle is bullish (green)
    - Current candle is bearish (red) and body fully engulfs previous body
    """
    return (
        is_bullish(prev)
        and is_bearish(c)
        and c["open"]  > prev["close"]
        and c["close"] < prev["open"]
    )


def is_short_confirmation(candle: dict, prev_candle: dict | None = None) -> bool:
    """
    Returns True if candle is a valid short confirmation signal.
    """
    if is_shooting_star(candle):
        logger.debug("Pattern: Shooting Star detected")
        return True
    if prev_candle and is_bearish_engulfing(candle, prev_candle):
        logger.debug("Pattern: Bearish engulfing detected")
        return True
    return False
