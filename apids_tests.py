"""
Example-driven usage of APIDS: exchanges, endpoints, and terminal-friendly Loguru output.

Run from repo root:
    python apids_tests.py

The script runs a **full matrix**: one request for every (exchange, endpoint) pair declared in
apids.json, then short demos (parallel gather + concat).

Optional environment variables:
    ALPHAVANTAGE_API_KEY — required for Alpha Vantage candlesticks (otherwise that cell is skipped).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

import aiohttp
import pandas as pd
from loguru import logger

from apids import APIDS

CONFIG_PATH = Path(__file__).resolve().parent / "apids.json"

CONFIG_SKIP_KEYS = frozenset({"base_url", "key", "symbol_mapping"})


def list_configured_endpoints() -> List[Tuple[str, str]]:
    """Return sorted (exchange, endpoint) pairs that are defined in the loaded JSON config."""
    out: List[Tuple[str, str]] = []
    for ex_name in sorted(APIDS.CONFIG.keys()):
        ex_cfg = APIDS.CONFIG[ex_name]
        if not isinstance(ex_cfg, dict):
            continue
        for ep_name in sorted(ex_cfg.keys()):
            if ep_name in CONFIG_SKIP_KEYS:
                continue
            ep_cfg = ex_cfg[ep_name]
            if isinstance(ep_cfg, dict) and "mapping" in ep_cfg:
                out.append((ex_name, ep_name))
    return out


def log_matrix_coverage_plan(pairs: List[Tuple[str, str]]) -> None:
    """Log one line per exchange listing endpoints (DEBUG) — confirms at least one call per configured pair."""
    by_ex: Dict[str, List[str]] = {}
    for ex, ep in pairs:
        by_ex.setdefault(ex, []).append(ep)
    for ex in sorted(by_ex):
        logger.debug("Matrix will call {} → {}", ex, ", ".join(sorted(by_ex[ex])))


def matrix_call_params(exchange: str, endpoint: str) -> Tuple[str | None, Dict[str, Any]]:
    """Default universal symbol and kwargs so each venue's endpoint can succeed when the API is reachable."""
    symbol: str | None = "BTC/USDT"
    if exchange == "Coinbase":
        symbol = "BTC/USD"
    elif exchange == "Deribit":
        symbol = "BTC-PERPETUAL"
    elif exchange == "YahooFinance":
        symbol = "EUR/USD"
    elif exchange == "AlphaVantage":
        symbol = "IBM"

    kwargs: Dict[str, Any] = {}
    if endpoint == "candlesticks":
        if exchange == "Binance":
            kwargs = {"interval": "1h", "limit": 3}
        elif exchange == "Bybit":
            kwargs = {"interval": "60", "limit": 3}
        elif exchange == "OKX":
            kwargs = {"interval": "1H", "limit": 3}
        elif exchange == "Coinbase":
            kwargs = {"interval": 3600, "limit": 3}
        elif exchange == "Kraken":
            kwargs = {"interval": "60", "limit": 3}
        elif exchange == "YahooFinance":
            kwargs = {"interval": "1h"}
        elif exchange == "AlphaVantage":
            kwargs = {"interval": "5min"}
    elif endpoint == "order_book":
        kwargs = {"limit": 5}
    elif endpoint == "symbol_specs":
        # Bulk by default: symbol=None means “all symbols on this exchange”.
        # For exchanges that require a category/currency, caller can pass it via `symbol`.
        symbol = None

    return symbol, kwargs


def default_http_headers() -> Dict[str, str]:
    """Headers that satisfy picky CDNs (notably Yahoo) without breaking typical exchange APIs."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
    }


def setup_logging() -> None:
    """Single sink: time, level, location, message — optimized for reading in a terminal."""
    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<dim>{name}:{function}</dim> | "
            "<level>{message}</level>"
        ),
        level="DEBUG",
        colorize=True,
    )


def log_banner(title: str) -> None:
    logger.opt(colors=True).info("<bold><magenta>=== {} ===</magenta></bold>", title)


def log_subheading(title: str) -> None:
    logger.opt(colors=True).info("<bold>-- {}</bold>", title)


def _df_preview(df: pd.DataFrame, max_rows: int = 10, max_width: int = 120) -> str:
    with pd.option_context("display.max_rows", max_rows, "display.width", max_width, "display.max_columns", 20):
        return df.to_string()


def _failure_level_for_result(exchange: str, result: Dict[str, Any]) -> Literal["error", "warning"]:
    if result.get("status"):
        return "error"
    blob = " ".join(str(e.get("error", "")) for e in result.get("errors", []))
    if exchange == "YahooFinance" and "401" in blob:
        return "warning"
    return "error"


def log_fetch_result(
    label: str,
    result: Dict[str, Any],
    preview_rows: int = 6,
    *,
    failure_level: Literal["error", "warning"] = "error",
) -> None:
    """Log a single APIDS.fetch outcome with a compact DataFrame preview."""
    if result.get("status"):
        df = result["output"]
        n = len(df)
        logger.success("{} — OK ({} row(s), shape {})", label, n, getattr(df, "shape", ()))
        logger.debug("Index names: {}", list(df.index.names) if hasattr(df.index, "names") else df.index.name)
        logger.info("Preview:\n{}", _df_preview(df.head(preview_rows), max_rows=preview_rows))
    else:
        log_fail = logger.warning if failure_level == "warning" else logger.error
        log_fail("{} — FAILED", label)
        for err in result.get("errors", []):
            log_fail("  {}", err)


async def run_labeled(
    session: aiohttp.ClientSession,
    label: str,
    exchange: str,
    endpoint: str,
    symbol: str | None,
    **kwargs: Any,
) -> Dict[str, Any]:
    logger.debug(
        "Request: {} | exchange={} endpoint={} symbol={} kwargs={}",
        label,
        exchange,
        endpoint,
        symbol,
        kwargs,
    )
    result = await APIDS.fetch(session, exchange, endpoint, symbol, **kwargs)
    log_fetch_result(label, result, failure_level=_failure_level_for_result(exchange, result))
    return result


async def run_full_config_matrix(session: aiohttp.ClientSession) -> None:
    """One fetch per (exchange, endpoint) in apids.json."""
    log_banner("Full matrix — one call per exchange × endpoint in config")
    pairs = list_configured_endpoints()
    logger.info("Planned calls: {} (one per exchange × endpoint in config)", len(pairs))
    log_matrix_coverage_plan(pairs)

    ok = failed = skipped = 0
    for exchange, endpoint in pairs:
        label = f"{exchange}.{endpoint}"

        if exchange == "AlphaVantage" and endpoint == "candlesticks":
            key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
            if not key:
                logger.warning("SKIP {} (set ALPHAVANTAGE_API_KEY)", label)
                skipped += 1
                continue
            APIDS.CONFIG.setdefault("AlphaVantage", {})["key"] = key

        symbol, kwargs = matrix_call_params(exchange, endpoint)
        logger.debug("Matrix: {} symbol={} kwargs={}", label, symbol, kwargs)
        result = await APIDS.fetch(session, exchange, endpoint, symbol, **kwargs)

        if result.get("status"):
            ok += 1
            log_fetch_result(label, result)
        else:
            failed += 1
            log_fetch_result(label, result, failure_level=_failure_level_for_result(exchange, result))

    log_subheading("Matrix summary")
    logger.info(
        "Configured pairs: {} | OK: {} | failed: {} | skipped (no API key): {}",
        len(pairs),
        ok,
        failed,
        skipped,
    )


async def test_symbol_specs_bulk(session: aiohttp.ClientSession) -> None:
    log_banner("Test — symbol_specs bulk (symbol=None)")
    pairs = [(ex, ep) for ex, ep in list_configured_endpoints() if ep == "symbol_specs"]
    if not pairs:
        logger.warning("No symbol_specs endpoints found in config")
        return

    for exchange, _ in pairs:
        if exchange == "YahooFinance":
            continue

        # Allow special case: exchanges that require category/currency can accept it via symbol.
        # We keep the “clean default” first (symbol=None), then show one example override.
        if exchange == "AlphaVantage":
            continue  # no symbol_specs in config today; keep for future-proofing

        r = await run_labeled(session, f"{exchange} symbol_specs (bulk)", exchange, "symbol_specs", None)
        if r.get("status"):
            df = r["output"]
            if len(df) == 0:
                logger.error("{} symbol_specs returned empty DataFrame", exchange)
            if "digits" not in df.columns:
                logger.error("{} symbol_specs missing required column: digits", exchange)

        if exchange == "Bybit":
            await run_labeled(session, "Bybit symbol_specs (category=linear)", "Bybit", "symbol_specs", "linear")
        if exchange == "Deribit":
            await run_labeled(session, "Deribit symbol_specs (currency=ETH)", "Deribit", "symbol_specs", "ETH")


async def example_parallel_binance_okx(session: aiohttp.ClientSession) -> None:
    log_banner("Demo — parallel asyncio.gather (Binance + OKX current_price)")
    t1 = APIDS.fetch(session, "Binance", "current_price", "BTC/USDT")
    t2 = APIDS.fetch(session, "OKX", "current_price", "BTC/USDT")
    a, b = await asyncio.gather(t1, t2)
    log_fetch_result("parallel Binance", a, failure_level=_failure_level_for_result("Binance", a))
    log_fetch_result("parallel OKX", b, failure_level=_failure_level_for_result("OKX", b))


async def example_concat_successful_frames(session: aiohttp.ClientSession) -> None:
    log_banner("Demo — pd.concat on successful frames")
    tasks = [
        APIDS.fetch(session, "Binance", "current_price", "BTC/USDT"),
        APIDS.fetch(session, "Binance", "current_price", "ETH/USDT"),
    ]
    results = await asyncio.gather(*tasks)
    frames = [r["output"] for r in results if r.get("status")]
    if not frames:
        logger.error("No successful frames to concat")
        for r in results:
            for e in r.get("errors", []):
                logger.error("{}", e)
        return
    stacked = pd.concat(frames)
    logger.success("Concat shape: {}", stacked.shape)
    logger.info("Stacked preview:\n{}", _df_preview(stacked))


async def main() -> None:
    setup_logging()
    logger.info("Config: {}", CONFIG_PATH)
    APIDS.load_config(str(CONFIG_PATH))

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(headers=default_http_headers(), timeout=timeout) as session:
        await run_full_config_matrix(session)
        await test_symbol_specs_bulk(session)
        await example_parallel_binance_okx(session)
        await example_concat_successful_frames(session)

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
