import logging
from config import MIN_RR_RATIO, RISK_PCT, STAKE, MULTIPLIER, MAX_DAILY_LOSS_PCT

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# SL / TP Price Calculation
# ──────────────────────────────────────────────────────────────

def calculate_sl_price_long(confirmation_candle: dict) -> float:
    """
    SL for longs = 50% of candle body below the sweep candle's LOW wick.
    This gives a tight but fair stop.
    """
    body     = abs(confirmation_candle["close"] - confirmation_candle["open"])
    half_body = body * 0.50
    sl_price  = confirmation_candle["low"] - half_body
    return round(sl_price, 5)


def calculate_sl_price_short(confirmation_candle: dict) -> float:
    """
    SL for shorts = 50% of candle body above the sweep candle's HIGH wick.
    """
    body      = abs(confirmation_candle["close"] - confirmation_candle["open"])
    half_body = body * 0.50
    sl_price  = confirmation_candle["high"] + half_body
    return round(sl_price, 5)


def calculate_tp_price_long(
    entry: float,
    sl: float,
    swing_high: float | None,
) -> float:
    """
    TP for longs:
    1. Target the nearest swing high if it gives >= MIN_RR_RATIO
    2. Otherwise use MIN_RR_RATIO × risk distance
    """
    risk = entry - sl
    if risk <= 0:
        risk = 0.0001  # safety guard

    if swing_high:
        reward = swing_high - entry
        rr     = reward / risk
        if rr >= MIN_RR_RATIO:
            return round(swing_high, 5)

    return round(entry + risk * MIN_RR_RATIO, 5)


def calculate_tp_price_short(
    entry: float,
    sl: float,
    swing_low: float | None,
) -> float:
    """TP for shorts."""
    risk = sl - entry
    if risk <= 0:
        risk = 0.0001

    if swing_low:
        reward = entry - swing_low
        rr     = reward / risk
        if rr >= MIN_RR_RATIO:
            return round(swing_low, 5)

    return round(entry - risk * MIN_RR_RATIO, 5)


# ──────────────────────────────────────────────────────────────
# Convert Price-Based SL/TP → USD amounts for Deriv Multipliers
# ──────────────────────────────────────────────────────────────

def price_to_usd(entry: float, target: float, stake: float, multiplier: int) -> float:
    """
    For Deriv Multipliers:
      position_value = stake × multiplier
      pnl = position_value × (price_change / entry)
    """
    price_change_pct = abs(target - entry) / entry
    usd_value        = stake * multiplier * price_change_pct
    return round(max(usd_value, 0.01), 2)


def get_sl_tp_usd(
    entry: float,
    sl_price: float,
    tp_price: float,
    stake: float   = STAKE,
    multiplier: int = MULTIPLIER,
) -> tuple[float, float]:
    sl_usd = price_to_usd(entry, sl_price, stake, multiplier)
    tp_usd = price_to_usd(entry, tp_price, stake, multiplier)
    logger.info(
        f"Risk calc | Entry: {entry} | SL price: {sl_price} (${sl_usd}) "
        f"| TP price: {tp_price} (${tp_usd}) | RR: {tp_usd/sl_usd:.2f}:1"
    )
    return sl_usd, tp_usd


# ──────────────────────────────────────────────────────────────
# Position Sizing
# ──────────────────────────────────────────────────────────────

def get_stake(balance: float, sl_usd: float) -> float:
    """
    Risk-based stake sizing:
    stake is capped so that hitting SL never costs more than RISK_PCT of balance.
    """
    max_risk   = balance * RISK_PCT        # e.g. $1000 × 2% = $20
    # sl_usd already represents the dollar loss if SL hits
    # We scale stake so that loss == max_risk
    if sl_usd <= 0:
        return STAKE
    scale = max_risk / sl_usd
    stake = round(STAKE * scale, 2)
    stake = max(1.0, min(stake, balance * 0.05))  # between $1 and 5% of balance
    return stake


# ──────────────────────────────────────────────────────────────
# Daily Loss Guard
# ──────────────────────────────────────────────────────────────

class DailyLossGuard:
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.max_loss         = starting_balance * MAX_DAILY_LOSS_PCT
        self.realized_loss    = 0.0
        self.trading_halted   = False

    def record_loss(self, amount: float):
        if amount > 0:
            self.realized_loss += amount
            logger.warning(f"Daily loss: ${self.realized_loss:.2f} / ${self.max_loss:.2f}")
        if self.realized_loss >= self.max_loss:
            self.trading_halted = True
            logger.critical(
                f"🛑 Daily loss limit hit (${self.realized_loss:.2f}). "
                "Trading halted until tomorrow."
            )

    def record_win(self, amount: float):
        # Wins don't count toward loss guard but log them
        logger.info(f"Win recorded: +${amount:.2f}")

    def can_trade(self) -> bool:
        return not self.trading_halted
