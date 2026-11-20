"""Read-only issuer and market-data retrieval with explicit vintage and feed metadata."""

import asyncio
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .calculators import technical_context
from .models import ResearchRequest


class DataSourceError(RuntimeError):
    pass


class PublicData:
    def __init__(self, transport=None):
        self.transport = transport

    async def _get(self, url, headers, params=None):
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code != 200:
                    raise DataSourceError(f"Data provider returned HTTP {response.status_code}")
                result = response.json()
                if not isinstance(result, dict):
                    raise DataSourceError("Data provider returned an invalid JSON object")
                return result
        except (httpx.HTTPError, ValueError):
            raise DataSourceError(
                "Data request failed or returned invalid JSON; no retry attempted"
            ) from None

    async def sec_filings(self, cik: str, cutoff: datetime) -> dict[str, Any]:
        cutoff = ResearchRequest(as_of=cutoff).as_of
        if not re.fullmatch(r"\d{1,10}", cik) or int(cik) == 0:
            raise ValueError("CIK must contain one to ten digits and be positive")
        user_agent = os.getenv("SEC_USER_AGENT", "").strip()
        if not user_agent:
            raise ValueError("Set SEC_USER_AGENT to your application name and contact email")
        url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
        data = await self._get(url, {"User-Agent": user_agent, "Accept": "application/json"})
        recent = data.get("filings", {}).get("recent", {})
        rows = []
        for index, accession in enumerate(recent.get("accessionNumber", [])):
            try:
                accepted = recent["acceptanceDateTime"][index]
                timestamp = datetime.fromisoformat(accepted.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    continue
                if timestamp > cutoff:
                    continue
                document = recent["primaryDocument"][index]
                if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
                    raise DataSourceError("Malformed accession identifier")
                if not re.fullmatch(r"[A-Za-z0-9_.\-]+", document):
                    raise DataSourceError("Malformed primary document name")
                rows.append(
                    {
                        "form": recent["form"][index],
                        "filed": recent["filingDate"][index],
                        "accepted_at": timestamp.isoformat(),
                        "accession": accession,
                        "report_date": recent["reportDate"][index],
                        "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}",
                    }
                )
            except (KeyError, IndexError, ValueError, TypeError):
                raise DataSourceError("Malformed SEC filing metadata") from None
        return {
            "cik": f"{int(cik):010d}",
            "name": data.get("name"),
            "source": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "cutoff": cutoff.isoformat(),
            "filings": rows,
            "coverage": "Current recent-submissions block only; older supplemental files and filing bodies are not fetched. Metadata does not verify financial claims.",
            "older_files": data.get("filings", {}).get("files", []),
        }

    async def latest_quotes(self, tickers: list[str], feed="iex") -> dict[str, Any]:
        request = ResearchRequest(tickers=tickers)
        if not request.tickers:
            raise ValueError("Provide at least one ticker")
        if feed not in ("iex", "sip", "delayed_sip"):
            raise ValueError("Feed must be iex, sip or delayed_sip")
        key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY for optional market-data tools")
        url = "https://data.alpaca.markets/v2/stocks/quotes/latest"
        data = await self._get(
            url, {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            {"symbols": ",".join(request.tickers), "feed": feed, "currency": "USD"},
        )
        retrieved = datetime.now(timezone.utc)
        quotes = data.get("quotes")
        if not isinstance(quotes, dict):
            raise DataSourceError("Market-data response is missing quotes")
        if set(quotes) - set(request.tickers):
            raise DataSourceError("Market-data response contains an unexpected symbol")
        symbols, errors = {}, {}
        for ticker in request.tickers:
            quote = quotes.get(ticker)
            if quote is None:
                errors[ticker] = "Quote unavailable for requested symbol"
                continue
            try:
                if not isinstance(quote, dict):
                    raise ValueError("Malformed quote")
                numbers = [quote[field] for field in ("bp", "ap", "bs", "as")]
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in numbers):
                    raise ValueError("Quote prices and sizes must be finite numbers")
                bid, ask, bid_size, ask_size = numbers
                if bid <= 0 or ask <= 0 or bid_size < 0 or ask_size < 0:
                    raise ValueError("Quote has no active price or invalid size")
                if bid > ask:
                    raise ValueError("Crossed bid and ask")
                stamp = datetime.fromisoformat(quote["t"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Quote timestamp requires a timezone")
                age = (retrieved - stamp).total_seconds()
                if age < -30:
                    raise ValueError("Quote timestamp is in the future beyond clock tolerance")
                if any(not isinstance(quote[field], str) or not re.fullmatch(r"[A-Za-z0-9]{1,8}", quote[field]) for field in ("bx", "ax")):
                    raise ValueError("Invalid quote exchange code")
                midpoint = bid + (ask - bid) / 2
                symbols[ticker] = {
                    "bid_price": bid, "ask_price": ask, "bid_size": bid_size, "ask_size": ask_size,
                    "bid_exchange": quote["bx"], "ask_exchange": quote["ax"],
                    "quoted_at": stamp.astimezone(timezone.utc).isoformat(),
                    "age_seconds": age, "older_than_60_seconds": age > 60,
                    "within_clock_skew_tolerance": age < 0,
                    "spread": ask - bid, "midpoint": midpoint, "spread_fraction": (ask - bid) / midpoint,
                }
            except (KeyError, TypeError, AttributeError, OverflowError):
                errors[ticker] = "Malformed quote fields"
            except ValueError as exc:
                errors[ticker] = str(exc) if str(exc) in {
                    "Malformed quote", "Quote prices and sizes must be finite numbers",
                    "Quote has no active price or invalid size", "Crossed bid and ask",
                    "Quote timestamp requires a timezone", "Quote timestamp is in the future beyond clock tolerance",
                    "Invalid quote exchange code",
                } else "Malformed quote timestamp"
        return {
            "source": url, "feed": feed, "currency": "USD", "retrieved_at": retrieved.isoformat(),
            "requested_symbols": request.tickers, "symbols": symbols, "errors": errors,
            "status": "complete" if not errors else "partial" if symbols else "unavailable",
            "future_clock_tolerance_seconds": 30,
            "limitations": "Latest available quotes, not historical cutoff data or guaranteed fills. IEX is one venue, not consolidated NBBO; SIP requires entitlement and delayed_sip is delayed by 15 minutes. Age is measured from source time, without assuming the market is open. Sizes are preserved in provider units; no share-unit conversion is assumed. Midpoints are valuation references, not executable prices.",
        }

    async def stock_history(
        self, tickers: list[str], cutoff: datetime, feed="iex", max_pages=5
    ) -> dict[str, Any]:
        request = ResearchRequest(tickers=tickers, as_of=cutoff)
        if not request.tickers:
            raise ValueError("Provide at least one ticker")
        if feed not in ("iex", "sip") or not 1 <= max_pages <= 20:
            raise ValueError("Feed must be iex/sip and page budget must be between 1 and 20")
        key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY for optional market-data tools")
        local_day = request.as_of.astimezone(ZoneInfo("America/New_York")).date()
        start = request.as_of - timedelta(days=5 * 366)
        params = {
            "symbols": ",".join(request.tickers),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": request.as_of.isoformat(),
            "adjustment": "all",
            "feed": feed,
            "asof": local_day.isoformat(),
            "limit": 10000,
            "sort": "asc",
        }
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        histories = {ticker: [] for ticker in request.tickers}
        seen_tokens = set()
        url = "https://data.alpaca.markets/v2/stocks/bars"
        for _ in range(max_pages):
            data = await self._get(url, headers, params)
            bars = data.get("bars")
            if not isinstance(bars, dict):
                raise DataSourceError("Market-data response is missing bars")
            for ticker, values in bars.items():
                if ticker not in histories or not isinstance(values, list):
                    raise DataSourceError("Market-data response contains an unexpected symbol")
                for bar in values:
                    try:
                        timestamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                        if timestamp.tzinfo is None:
                            raise ValueError()
                        if timestamp.astimezone(ZoneInfo("America/New_York")).date() < local_day:
                            histories[ticker].append(
                                {"timestamp": timestamp.isoformat(), "adjusted_close": float(bar["c"])}
                            )
                    except (KeyError, TypeError, ValueError):
                        raise DataSourceError("Malformed market bar") from None
            token = data.get("next_page_token")
            if not token:
                break
            if token in seen_tokens:
                raise DataSourceError("Market-data pagination repeated a token")
            seen_tokens.add(token)
            params["page_token"] = token
            await asyncio.sleep(0.2)
        else:
            raise DataSourceError("Market-data page budget exhausted; narrow the symbol list")
        result = {}
        for ticker, bars in histories.items():
            bars.sort(key=lambda bar: bar["timestamp"])
            if len({bar["timestamp"] for bar in bars}) != len(bars):
                raise DataSourceError("Duplicate daily bars would distort indicators")
            try:
                indicators = (
                    technical_context([bar["adjusted_close"] for bar in bars]) if len(bars) >= 2 else None
                )
            except ValueError:
                raise DataSourceError("Invalid adjusted market prices") from None
            result[ticker] = {
                "bars": bars,
                "technical_context": indicators,
                "status": "available" if indicators else "insufficient_history",
            }
        return {
            "source": url,
            "feed": feed,
            "adjustment": "all",
            "cutoff": request.as_of.isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "symbols": result,
            "limitations": "Excludes the cutoff's entire New York calendar day to avoid partial daily bars. IEX is one venue, not consolidated SIP. Adjusted historical closes are not executable entry quotes; later corporate-action adjustments are not point-in-time backtest data.",
        }
