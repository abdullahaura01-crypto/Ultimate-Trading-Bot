import json
import time
import threading
import logging
import websocket
from config import DERIV_APP_ID, DERIV_API_TOKEN

logger = logging.getLogger(__name__)


class DerivClient:
    WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

    def __init__(self):
        self.ws               = None
        self.authorized       = False
        self.connected        = False
        self._lock            = threading.Lock()
        self._req_id          = 0
        self._callbacks       = {}   # msg_type -> [callback, ...]
        self._pending         = {}   # req_id   -> {"event": Event, "data": []}
        self.open_trades      = {}   # contract_id -> trade info
        self.balance          = 0.0
        self.account_currency = "USD"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self):
        logger.info("Connecting to Deriv WebSocket...")
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open    = self._on_open,
            on_message = self._on_message,
            on_error   = self._on_error,
            on_close   = self._on_close,
        )
        t = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10}
        )
        t.daemon = True
        t.start()
        for _ in range(20):
            if self.connected:
                break
            time.sleep(0.5)
        else:
            raise ConnectionError("Could not connect to Deriv WebSocket")

    def _on_open(self, ws):
        self.connected = True
        logger.info("WebSocket connected - authorizing...")
        # Send authorize WITHOUT using _send_raw so no req_id is added.
        # This prevents the authorize response from being swallowed by
        # the _pending handler before _on_message can set self.authorized.
        token = DERIV_API_TOKEN.replace("pat_", "")
        ws.send(json.dumps({"authorize": token}))

    def _on_close(self, ws, code, msg):
        self.connected  = False
        self.authorized = False
        logger.warning(f"WebSocket closed ({code}). Reconnecting in 5s...")
        time.sleep(5)
        self.connect()

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")

    # ------------------------------------------------------------------
    # Message routing  (FIXED: always process msg_type handlers FIRST,
    # then also resolve any pending request waiter)
    # ------------------------------------------------------------------
    def _on_message(self, ws, raw):
        data = json.loads(raw)

        # Log errors but don't stop processing
        if "error" in data:
            code = data["error"].get("code", "?")
            msg  = data["error"].get("message", "?")
            logger.error(f"API error [{code}]: {msg}")

        msg_type = data.get("msg_type", "")

        # --- Always handle authorize first so self.authorized is set ---
        if msg_type == "authorize":
            if "error" not in data:
                self.authorized = True
                info = data.get("authorize", {})
                self.balance          = float(info.get("balance", 0))
                self.account_currency = info.get("currency", "USD")
                logger.info(f"Authorized | Balance: {self.balance} {self.account_currency}")
            return  # authorize responses never need pending resolution

        # --- Balance updates ---
        if msg_type == "balance":
            bal = data.get("balance", {})
            if isinstance(bal, dict):
                self.balance = float(bal.get("balance", self.balance))

        # --- Resolve one-shot pending request ---
        req_id = data.get("req_id")
        if req_id and req_id in self._pending:
            self._pending[req_id]["data"].append(data)
            self._pending[req_id]["event"].set()
            return

        # --- Route to subscribed callbacks ---
        for cb in self._callbacks.get(msg_type, []):
            try:
                cb(data)
            except Exception as e:
                logger.exception(f"Callback error for {msg_type}: {e}")

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------
    def _send_raw(self, payload: dict) -> int:
        with self._lock:
            self._req_id += 1
            payload["req_id"] = self._req_id
            self.ws.send(json.dumps(payload))
            return self._req_id

    def _send_wait(self, payload: dict, timeout: float = 15) -> dict | None:
        """Send and block until response arrives."""
        event  = threading.Event()
        result = []
        req_id = self._send_raw(payload)
        self._pending[req_id] = {"event": event, "data": result}
        event.wait(timeout=timeout)
        self._pending.pop(req_id, None)
        return result[0] if result else None

    def on(self, msg_type: str, callback):
        self._callbacks.setdefault(msg_type, []).append(callback)

    def ping(self):
        """Send a lightweight ping to keep the connection alive."""
        try:
            self._send_raw({"ping": 1})
        except Exception as e:
            logger.warning(f"Ping failed: {e}")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def get_candles(self, symbol: str, granularity: int, count: int = 150) -> list:
        resp = self._send_wait({
            "ticks_history": symbol,
            "style"        : "candles",
            "granularity"  : granularity,
            "count"        : count,
            "end"          : "latest",
        })
        if resp and "candles" in resp:
            return resp["candles"]
        logger.error("Failed to fetch candles")
        return []

    def subscribe_candles(self, symbol: str, granularity: int, callback):
        """Subscribe to live candle updates."""
        self.on("ohlc", callback)
        self._send_raw({
            "ticks_history": symbol,
            "style"        : "candles",
            "granularity"  : granularity,
            "count"        : 1,
            "end"          : "latest",
            "subscribe"    : 1,
        })
        logger.info(f"Subscribed to {symbol} M{granularity // 60} candles")

    # ------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------
    def buy_multiplier(
        self,
        symbol    : str,
        direction : str,
        stake     : float,
        sl_usd    : float,
        tp_usd    : float,
        multiplier: int = 10,
    ) -> dict | None:
        contract_type = "MULTUP" if direction == "BUY" else "MULTDOWN"
        resp = self._send_wait({
            "buy"        : 1,
            "price"      : stake,
            "parameters" : {
                "contract_type": contract_type,
                "symbol"       : symbol,
                "multiplier"   : multiplier,
                "currency"     : self.account_currency,
                "amount"       : stake,
                "stop_loss"    : round(sl_usd, 2),
                "take_profit"  : round(tp_usd, 2),
                "basis"        : "stake",
            },
        })
        if resp and "buy" in resp:
            contract_id = resp["buy"]["contract_id"]
            self.open_trades[contract_id] = {
                "direction": direction,
                "stake"    : stake,
                "sl_usd"   : sl_usd,
                "tp_usd"   : tp_usd,
                "buy_price": resp["buy"]["buy_price"],
            }
            logger.info(
                f"Trade placed: {direction} {symbol} | "
                f"stake=${stake} | SL=${sl_usd} | TP=${tp_usd}"
            )
            return resp["buy"]
        logger.error(f"Trade failed: {resp}")
        return None

    def sell_contract(self, contract_id: int) -> bool:
        resp = self._send_wait({"sell": contract_id, "price": 0})
        if resp and "sell" in resp:
            self.open_trades.pop(contract_id, None)
            logger.info(f"Contract {contract_id} closed")
            return True
        return False

    def get_balance(self) -> float:
        """One-shot balance fetch."""
        resp = self._send_wait({"balance": 1})
        if resp and "balance" in resp:
            b = resp["balance"]
            if isinstance(b, dict):
                self.balance = float(b.get("balance", self.balance))
        return self.balance

    def wait_authorized(self, timeout: float = 15) -> bool:
        for _ in range(int(timeout * 2)):
            if self.authorized:
                return True
            time.sleep(0.5)
        return False
