"""Opt-in gold/silver reference data through the public DataAdapter protocol.

Only daily USD averages and current spot are supported. Payloads and the cache
live in memory; credentials follow the other native vendors' environment setup.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path

import requests

BASE = "https://api.gold-api.com"
ATTRIBUTION = "Gold reference data: Gold API https://gold-api.com/"
SPOT_CLOCK_SKEW_SECONDS = 5


class GoldDataUnavailable(RuntimeError):
    pass


class GoldHistoryNotConfigured(GoldDataUnavailable):
    code = "gold_history_not_configured"


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Exact positive source number required")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid source number") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("Invalid source number")
    return str(number)


def history_day(value):
    """Gold API groups UTC days, including naive ISO midnight day labels."""
    if not isinstance(value,str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ]00:00:00(?:\.0{1,6})?(?:Z|\+00:00)?)?",value):
        raise ValueError("Complete UTC calendar day required")
    # The provider documents UTC grouping. This assumption is local to its day
    # labels, never applied to broker records or arbitrary source timestamps.
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def spot_is_fresh(updated, now):
    """Allow bounded clock skew, preserving the provider's original timestamp."""
    return (updated.tzinfo is not None and now.tzinfo is not None
        and timedelta(seconds=-SPOT_CLOCK_SKEW_SECONDS)<=now-updated<=timedelta(minutes=15))


class GoldReferenceAdapter:
    """Prepared current spot and completed daily averages; never broker prices."""

    name = "gold_api"
    clock_skew_tolerance_seconds = SPOT_CLOCK_SKEW_SECONDS

    def __init__(self, *, metal_symbol="XAU", ticker="XAU-USD-SPOT", quote_currency="USD",
                 history_days=90, max_requests=4, enabled=False, licensed=False,
                 api_key=None, client=None, clock=lambda: datetime.now(timezone.utc), sleep=time.sleep):
        if metal_symbol not in {"XAU", "XAG"} or ticker != metal_symbol+"-USD-SPOT" or quote_currency != "USD":
            raise ValueError("Explicit USD metal spot identity required")
        if type(history_days) is not int or not 31 <= history_days <= 365 or type(max_requests) is not int or not 2 <= max_requests <= 20:
            raise ValueError("Bounded gold source configuration required")
        if enabled is not True or licensed is not True:
            raise ValueError("Explicit source policy required")
        self.symbol, self.ticker, self.history_days, self.max_requests = metal_symbol, ticker, history_days, max_requests
        self.api_key = os.getenv("GOLD_API_KEY", "") if api_key is None else api_key
        self.http, self.clock, self.sleep = client, clock, sleep
        self.client = self  # Source admission/receipt protocol used by callers.
        self.requests, self.stopped, self.retry_at = 0, False, None
        self.receipts, self.quote, self.history, self.tool_states = {}, None, [], {}
        self.implementation = sha256(Path(__file__).read_bytes()).hexdigest()
        self.lock = threading.RLock()
        self.captured_at = None
        self.analysis_date = None

    def fail(self):
        self.stopped = True
        self.retry_at = self.clock()+timedelta(hours=1)
        raise GoldDataUnavailable("Gold source unavailable; no fallback") from None

    def _get(self, path, params=None, authenticated=False):
        if self.stopped or self.requests >= self.max_requests:
            self.fail()
        if self.http is None:
            self.http = requests.Session()
            self.http.trust_env = False
        headers = {"Accept":"application/json", "User-Agent":"TradingAgents-gold-reference/1.0"}
        if authenticated:
            headers["x-api-key"] = self.api_key
        if self.requests:
            self.sleep(1)
        self.requests += 1
        # Persisted admission metadata can hold the hour boundary, never the key.
        self.retry_at = self.clock()+timedelta(hours=1)
        try:
            with self.http.get(BASE+path, params=params, headers=headers, timeout=10, stream=True, allow_redirects=False) as response:
                if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0] != "application/json":
                    self.fail()
                content = bytearray()
                for chunk in response.iter_content(16384):
                    content.extend(chunk)
                    if len(content) > 500000:
                        self.fail()
                data = json.loads(content, parse_float=Decimal)
                receipt = {"url":str(response.url), "retrieved_at":self.clock().isoformat(),
                    "provider":self.name, "sha256":sha256(content).hexdigest()}
                return data,receipt
        except (requests.RequestException, ValueError, UnicodeError):
            self.fail()

    def prepare(self):
        with self.lock:
            if self.quote is not None:
                return
            if not self.api_key:
                raise GoldHistoryNotConfigured("GOLD_API_KEY is required for the free history endpoint")
            now = self.clock()
            if now.tzinfo is None:
                raise ValueError("Aware source clock required")
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end-timedelta(days=self.history_days)
            # History first: avoid wasting a spot request when required history fails.
            data, receipt = self._get("/history", {"symbol":self.symbol,"startTimestamp":int(start.timestamp()),
                "endTimestamp":int(end.timestamp())-1,"groupBy":"day","aggregation":"avg","orderBy":"asc"}, True)
            try:
                if not isinstance(data, list) or not 31 <= len(data) <= self.history_days:
                    raise ValueError("Bounded daily history required")
                points = []
                for row in data:
                    day = history_day(row["day"])
                    if not start <= day < end or points and not points[-1][0] < day:
                        raise ValueError("Invalid history ordering/window")
                    points.append((day,positive(row["avg_price"])))
                if (end-points[-1][0] > timedelta(days=4) or points[-1][0]-points[0][0] < timedelta(days=30)
                        or any(b[0]-a[0] > timedelta(days=4) for a,b in zip(points,points[1:]))):
                    raise ValueError("Stale or incomplete history")
                self.history = points
                self.receipts[receipt["url"]] = receipt
                quote, receipt = self._get("/price/"+self.symbol+"/USD")
                updated = datetime.fromisoformat(quote["updatedAt"])
                price = positive(quote["price"])
                if (quote.get("symbol") != self.symbol or quote.get("currency") != "USD"
                        or quote.get("name") != {"XAU":"Gold","XAG":"Silver"}[self.symbol]
                        or not spot_is_fresh(updated,self.clock())):
                    raise ValueError("Invalid current spot")
                self.quote = {"price":price,"source_updated_at":updated.isoformat()}
                self.receipts[receipt["url"]] = receipt
                self.captured_at = self.clock()
            except (KeyError, TypeError, ValueError, OverflowError):
                self.fail()

    def fingerprint(self):
        return sha256(json.dumps({"provider":self.name,"ticker":self.ticker,"history_days":self.history_days,
            "max_requests":self.max_requests,"implementation":self.implementation},sort_keys=True).encode()).hexdigest()

    def instrument_context(self, ticker, asset_type, trade_date):
        if ticker != self.ticker or asset_type != "commodity" or self.quote is None:
            raise GoldDataUnavailable("Prepared commodity identity required")
        day = datetime.strptime(trade_date,"%Y-%m-%d").date()
        if not 0 <= (day-self.captured_at.date()).days <= 1:
            raise GoldDataUnavailable("Current research date required")
        self.analysis_date = day
        return (f"Gold API metal spot reference {ticker}, USD per troy ounce. Broker holdings remain native grams of a distinct product. "
            "Never substitute shares, contracts or ounces for those grams. Historical observations are UTC daily averages, not closes or OHLC bars. "
            "Volume and OHLC indicators are unsupported. News/macro claims require separately retrieved evidence; disclose missing coverage. "+ATTRIBUTION)

    def get_data(self, method, *args, **kwargs):
        if method not in {"get_stock_data","get_verified_market_snapshot"}:
            return "DATA_UNAVAILABLE: this gold source does not supply news, macro series, OHLC indicators or company fundamentals."
        with self.lock:
            try:
                ticker = args[0] if args else kwargs.get("symbol")
                if ticker != self.ticker or self.quote is None:
                    raise ValueError("Prepared gold identity required")
                end = (args[2] if len(args)>2 else kwargs.get("end_date")) if method=="get_stock_data" else (args[1] if len(args)>1 else kwargs.get("curr_date"))
                end_day = datetime.strptime(end,"%Y-%m-%d").date()
                if end_day != (self.analysis_date or self.captured_at.date()) or not spot_is_fresh(datetime.fromisoformat(self.quote["source_updated_at"]),self.clock()):
                    raise ValueError("Current, fresh snapshot required")
                start = datetime.strptime(args[1] if len(args)>1 else kwargs.get("start_date"),"%Y-%m-%d").date() if method=="get_stock_data" else end_day-timedelta(days=30)
                points = [(day,value) for day,value in self.history if start <= day.date() < end_day]
                if not points:
                    raise ValueError("Requested history unavailable")
                self.tool_states[method] = "available"
                return (json.dumps({"ticker":self.ticker,"currency":"USD","unit":"troy_ounce","current_spot":self.quote,
                    "history_measure":"UTC daily average; not OHLC or close", "source_receipts":list(self.receipts.values()), "daily_samples":[[day.date().isoformat(),value] for day,value in points]},sort_keys=True)
                    +"\n"+ATTRIBUTION+"\nHistorical/news/indicator limitations must be disclosed. No FX conversion or broker revaluation.")
            except (KeyError, TypeError, ValueError):
                self.tool_states[method] = "unavailable"
                return "DATA_UNAVAILABLE: gold snapshot/history identity, date or freshness check failed."

    def coverage(self):
        return {"schema_version":"1.0","ticker":self.ticker,"provider":self.name,"currency":"USD","unit":"troy_ounce",
            "captured_at":self.captured_at.isoformat() if self.captured_at else None,
            "spot_as_of":self.quote["source_updated_at"] if self.quote else None,
            "history_start":self.history[0][0].date().isoformat() if self.history else None,
            "history_end":self.history[-1][0].date().isoformat() if self.history else None,
            "history_count":len(self.history),"history_measure":"daily_average",
            "required_tools":dict(self.tool_states),"optional_unavailable":["news","macro","ohlc_indicators"]}

    def close(self):
        if self.http is not None:
            self.http.close()
        self.api_key = ""
        self.history.clear()
        self.quote = None


def history_configured():
    """Presence only, without returning a credential or opening an HTTP session."""
    return bool(os.getenv("GOLD_API_KEY"))
