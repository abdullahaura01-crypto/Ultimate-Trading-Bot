import logging
from config import ZONE_TOLERANCE, SWING_LOOKBACK, ZONE_MIN_TOUCHES

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Swing High / Low Detection
# ──────────────────────────────────────────────────────────────

def find_swing_lows(candles: list, n: int = SWING_LOOKBACK) -> list[tuple[int, float]]:
    """
    Return (index, low) for every swing low in the candle list.
    A swing low = lowest candle among N candles on each side.
    """
    results = []
    for i in range(n, len(candles) - n):
        pivot = candles[i]["low"]
        if all(candles[j]["low"] >= pivot for j in range(i - n, i + n + 1) if j != i):
            results.append((i, pivot))
    return results


def find_swing_highs(candles: list, n: int = SWING_LOOKBACK) -> list[tuple[int, float]]:
    """Return (index, high) for every swing high."""
    results = []
    for i in range(n, len(candles) - n):
        pivot = candles[i]["high"]
        if all(candles[j]["high"] <= pivot for j in range(i - n, i + n + 1) if j != i):
            results.append((i, pivot))
    return results


# ──────────────────────────────────────────────────────────────
# Zone Building
# ──────────────────────────────────────────────────────────────

def build_demand_zones(candles: list) -> list[dict]:
    """
    Find demand (support) zones from double/triple bottoms.
    Returns list of zone dicts sorted by most recent first.
    """
    swing_lows = find_swing_lows(candles)
    zones      = []
    used       = set()

    for i, (idx_a, low_a) in enumerate(swing_lows):
        if i in used:
            continue

        cluster = [(idx_a, low_a)]

        for j, (idx_b, low_b) in enumerate(swing_lows):
            if j <= i or j in used:
                continue
            if abs(low_a - low_b) / low_a <= ZONE_TOLERANCE:
                cluster.append((idx_b, low_b))
                used.add(j)

        if len(cluster) >= ZONE_MIN_TOUCHES:
            used.add(i)
            zone_bottom = min(p for _, p in cluster)
            zone_top    = max(p for _, p in cluster) * (1 + ZONE_TOLERANCE)
            zones.append({
                "type"       : "demand",
                "bottom"     : round(zone_bottom, 5),
                "top"        : round(zone_top, 5),
                "touches"    : len(cluster),
                "last_index" : max(idx for idx, _ in cluster),
            })

    # Sort: most recent zone first
    zones.sort(key=lambda z: z["last_index"], reverse=True)
    logger.debug(f"Found {len(zones)} demand zones")
    return zones


def build_supply_zones(candles: list) -> list[dict]:
    """
    Find supply (resistance) zones from double/triple tops.
    """
    swing_highs = find_swing_highs(candles)
    zones       = []
    used        = set()

    for i, (idx_a, high_a) in enumerate(swing_highs):
        if i in used:
            continue

        cluster = [(idx_a, high_a)]

        for j, (idx_b, high_b) in enumerate(swing_highs):
            if j <= i or j in used:
                continue
            if abs(high_a - high_b) / high_a <= ZONE_TOLERANCE:
                cluster.append((idx_b, high_b))
                used.add(j)

        if len(cluster) >= ZONE_MIN_TOUCHES:
            used.add(i)
            zone_top    = max(p for _, p in cluster)
            zone_bottom = min(p for _, p in cluster) * (1 - ZONE_TOLERANCE)
            zones.append({
                "type"       : "supply",
                "bottom"     : round(zone_bottom, 5),
                "top"        : round(zone_top, 5),
                "touches"    : len(cluster),
                "last_index" : max(idx for idx, _ in cluster),
            })

    zones.sort(key=lambda z: z["last_index"], reverse=True)
    logger.debug(f"Found {len(zones)} supply zones")
    return zones


# ──────────────────────────────────────────────────────────────
# Liquidity Sweep Detection
# ──────────────────────────────────────────────────────────────

def detect_sweep_and_reverse_long(candle: dict, zone: dict) -> bool:
    """
    Buy sweep condition:
    1. Candle LOW wicks below the demand zone bottom (stop hunts retail buyers)
    2. Candle CLOSES back above the zone bottom (institutional reversal)
    """
    swept    = candle["low"]   < zone["bottom"]
    reversed_= candle["close"] > zone["bottom"]
    return swept and reversed_


def detect_sweep_and_reverse_short(candle: dict, zone: dict) -> bool:
    """
    Sell sweep condition:
    1. Candle HIGH wicks above the supply zone top (stop hunts retail sellers)
    2. Candle CLOSES back below the zone top (institutional reversal)
    """
    swept    = candle["high"]  > zone["top"]
    reversed_= candle["close"] < zone["top"]
    return swept and reversed_


# ──────────────────────────────────────────────────────────────
# Swing High/Low for TP Targeting
# ──────────────────────────────────────────────────────────────

def get_nearest_swing_high(candles: list, from_index: int) -> float | None:
    """Return the nearest swing high above current price (for BUY TP)."""
    highs = find_swing_highs(candles[:from_index])
    if not highs:
        return None
    current_close = candles[from_index]["close"]
    above = [(idx, h) for idx, h in highs if h > current_close]
    if not above:
        return None
    return min(above, key=lambda x: x[1])[1]  # nearest high above


def get_nearest_swing_low(candles: list, from_index: int) -> float | None:
    """Return the nearest swing low below current price (for SELL TP)."""
    lows = find_swing_lows(candles[:from_index])
    if not lows:
        return None
    current_close = candles[from_index]["close"]
    below = [(idx, l) for idx, l in lows if l < current_close]
    if not below:
        return None
    return max(below, key=lambda x: x[1])[1]  # nearest low below
