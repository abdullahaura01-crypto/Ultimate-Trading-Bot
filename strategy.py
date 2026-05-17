import logging
from config import (
    SYMBOL, MULTIPLIER, STAKE, MAX_OPEN_TRADES,
    PYRAMID_ENABLED, STRUCTURE_BREAK_PIPS
)
from zone_detector import (
    build_demand_zones, build_supply_zones,
    detect_sweep_and_reverse_long, detect_sweep_and_reverse_short,
    get_nearest_swing_high, get_nearest_swing_low,
)
from candle_patterns import is_long_confirmation, is_short_confirmation
from risk_manager import (
    calculate_sl_price_long, calculate_sl_price_short,
    calculate_tp_price_long, calculate_tp_price_short,
    get_sl_tp_usd, get_stake,
)

logger = logging.getLogger(__name__)


class SMCStrategy:
    """
    Smart Money Concept — Liquidity Sweep Strategy
    -----------------------------------------------
    Waits for institutional liquidity grabs (stop hunts) at
    double/triple bottom or top zones, then enters on a
    reversal confirmation candle.
    """

    def __init__(self, client, loss_guard):
        self.client      = client
        self.loss_guard  = loss_guard
        self.candles     = []          # rolling candle window
        self.active_long = None        # current long trade metadata
        self.active_short= None        # current short trade metadata
        self.pyramid_done= False       # only pyramid once per trade

    # ──────────────────────────────────────────────────────────
    # Called on every new closed M15 candle
    # ──────────────────────────────────────────────────────────

    def on_candle(self, candle: dict):
        self.candles.append(candle)
        if len(self.candles) > 200:        # keep rolling window
            self.candles.pop(0)

        if len(self.candles) < 30:         # not enough history yet
            return

        if not self.loss_guard.can_trade():
            return

        open_count = len(self.client.open_trades)

        # ── Check pyramid opportunity first ──────────────────
        if PYRAMID_ENABLED and open_count > 0 and open_count < MAX_OPEN_TRADES:
            self._check_pyramid(candle)
            return

        # ── No room for new trade ─────────────────────────────
        if open_count >= MAX_OPEN_TRADES:
            return

        # ── Scan for new setups ───────────────────────────────
        self._check_long_setup(candle)
        self._check_short_setup(candle)

    # ──────────────────────────────────────────────────────────
    # Long (Buy) Setup
    # ──────────────────────────────────────────────────────────

    def _check_long_setup(self, candle: dict):
        demand_zones = build_demand_zones(self.candles)
        if not demand_zones:
            return

        prev_candle  = self.candles[-2] if len(self.candles) >= 2 else None

        for zone in demand_zones:
            # Step 1: Liquidity sweep — wick below zone, close above
            if not detect_sweep_and_reverse_long(candle, zone):
                continue

            # Step 2: Confirmation candle (hammer or bullish engulfing)
            if not is_long_confirmation(candle, prev_candle):
                continue

            # Step 3: Calculate SL / TP
            entry    = candle["close"]
            sl_price = calculate_sl_price_long(candle)
            if sl_price >= entry:
                continue   # malformed candle

            swing_high = get_nearest_swing_high(self.candles, len(self.candles) - 1)
            tp_price   = calculate_tp_price_long(entry, sl_price, swing_high)

            sl_usd, tp_usd = get_sl_tp_usd(entry, sl_price, tp_price)
            stake = get_stake(self.client.balance, sl_usd)

            logger.info(
                f"📈 LONG SETUP | Zone: {zone['bottom']:.5f}–{zone['top']:.5f} "
                f"| Touches: {zone['touches']} | Entry: {entry}"
            )

            # Step 4: Execute
            result = self.client.buy_multiplier(
                symbol     = SYMBOL,
                direction  = "BUY",
                stake      = stake,
                sl_usd     = sl_usd,
                tp_usd     = tp_usd,
                multiplier = MULTIPLIER,
            )

            if result:
                self.active_long   = {
                    "zone"      : zone,
                    "entry"     : entry,
                    "sl_price"  : sl_price,
                    "tp_price"  : tp_price,
                    "contract_id": result["contract_id"],
                }
                self.pyramid_done = False
            break  # one trade per candle

    # ──────────────────────────────────────────────────────────
    # Short (Sell) Setup
    # ──────────────────────────────────────────────────────────

    def _check_short_setup(self, candle: dict):
        supply_zones = build_supply_zones(self.candles)
        if not supply_zones:
            return

        prev_candle = self.candles[-2] if len(self.candles) >= 2 else None

        for zone in supply_zones:
            if not detect_sweep_and_reverse_short(candle, zone):
                continue

            if not is_short_confirmation(candle, prev_candle):
                continue

            entry    = candle["close"]
            sl_price = calculate_sl_price_short(candle)
            if sl_price <= entry:
                continue

            swing_low = get_nearest_swing_low(self.candles, len(self.candles) - 1)
            tp_price  = calculate_tp_price_short(entry, sl_price, swing_low)

            sl_usd, tp_usd = get_sl_tp_usd(entry, sl_price, tp_price)
            stake = get_stake(self.client.balance, sl_usd)

            logger.info(
                f"📉 SHORT SETUP | Zone: {zone['bottom']:.5f}–{zone['top']:.5f} "
                f"| Touches: {zone['touches']} | Entry: {entry}"
            )

            result = self.client.buy_multiplier(
                symbol     = SYMBOL,
                direction  = "SELL",
                stake      = stake,
                sl_usd     = sl_usd,
                tp_usd     = tp_usd,
                multiplier = MULTIPLIER,
            )

            if result:
                self.active_short  = {
                    "zone"       : zone,
                    "entry"      : entry,
                    "sl_price"   : sl_price,
                    "tp_price"   : tp_price,
                    "contract_id": result["contract_id"],
                }
                self.pyramid_done = False
            break

    # ──────────────────────────────────────────────────────────
    # Pyramid (Entry 2) — add to winning position only
    # ──────────────────────────────────────────────────────────

    def _check_pyramid(self, candle: dict):
        if self.pyramid_done:
            return

        current_price = candle["close"]

        # Pyramid long: price breaks above local structure
        if self.active_long:
            entry   = self.active_long["entry"]
            already_won = current_price > entry + STRUCTURE_BREAK_PIPS

            if already_won:
                logger.info("📈+ PYRAMID: Adding to winning long position")
                sl_price = calculate_sl_price_long(candle)
                swing_high = get_nearest_swing_high(self.candles, len(self.candles) - 1)
                tp_price   = calculate_tp_price_long(current_price, sl_price, swing_high)
                sl_usd, tp_usd = get_sl_tp_usd(current_price, sl_price, tp_price)
                stake = get_stake(self.client.balance, sl_usd)

                result = self.client.buy_multiplier(
                    SYMBOL, "BUY", stake, sl_usd, tp_usd, MULTIPLIER
                )
                if result:
                    self.pyramid_done = True

        # Pyramid short: price breaks below local structure
        elif self.active_short:
            entry     = self.active_short["entry"]
            already_won = current_price < entry - STRUCTURE_BREAK_PIPS

            if already_won:
                logger.info("📉+ PYRAMID: Adding to winning short position")
                sl_price  = calculate_sl_price_short(candle)
                swing_low = get_nearest_swing_low(self.candles, len(self.candles) - 1)
                tp_price  = calculate_tp_price_short(current_price, sl_price, swing_low)
                sl_usd, tp_usd = get_sl_tp_usd(current_price, sl_price, tp_price)
                stake = get_stake(self.client.balance, sl_usd)

                result = self.client.buy_multiplier(
                    SYMBOL, "SELL", stake, sl_usd, tp_usd, MULTIPLIER
                )
                if result:
                    self.pyramid_done = True
