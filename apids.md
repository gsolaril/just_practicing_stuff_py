# 📘 Project Briefing: Universal Market Data Integrator

## 1. Project Objective
To build a **fully data-driven, asynchronous Python integration layer** capable of fetching market data from any financial exchange (Crypto, Forex, or Stocks) without hardcoded exchange-specific logic. The system is designed to be **horizontally scalable**, where adding a new exchange or endpoint requires only a JSON configuration update.

---

## 2. Core Architectural Principles
*   **JSON-as-Operating-System:** All operative logic—URL construction, argument mapping, response traversal, and symbol transformation—is stored in an external `config.json`.
*   **Universal Interface:** A single Python class provides homogeneous methods that return standardized Pandas DataFrames.
*   **Non-Blocking Parallelism:** Built on `asyncio` and `aiohttp` to execute multiple requests across different exchanges simultaneously.
*   **Strict Error Encapsulation:** Every call returns a consistent dictionary structure to ensure stability.

---

## 3. The Operative JSON Schema
The configuration file dictates the behavior for each exchange using the following components:

*   **Symbol Mapping (Regex):** Transforms a universal symbol (e.g., `BTC/USDT`) into exchange formats (e.g., `BTCUSDT`, `BTC-USDT`, or `EURUSD=X`).
    *   *Pattern:* `([^/]+)/([^/]+)`
    *   *Replacement:* `\1\2` (or `\1-\2`, etc.)
*   **Endpoint Definition:**
    *   **Method:** HTTP verb (`GET`, `POST`).
    *   **Path:** Supports path variable injection (e.g., `/products/{symbol}/ticker`).
    *   **Args:** Maps internal arguments to exchange-specific parameters.
    *   **Mapping (Traversal Path):** A list-based navigation instruction:
        *   *Integers:* Array indices.
        *   *Strings:* Dictionary keys.
        *   `*FIRST_KEY*`: Wild-card for dynamic top-level keys (e.g., Kraken).
        *   `root`: Defines the starting point for list-based data.

---

## 4. Standardized Data Outputs
Every method returns: `{"status": <bool>, "output": <DataFrame>, "errors": <list>}`

### DataFrame Structure Requirements:


| Endpoint | Index | Key Columns |
| :--- | :--- | :--- |
| **current_price** | `[exchange, symbol]` | `ask`, `bid` |
| **candlesticks** | `[exchange, symbol, timestamp]` | `open`, `high`, `low`, `close`, `volume` |
| **order_book** | `[exchange, symbol, level]` | `ask_price`, `bid_price`, `ask_volume`, `bid_volume` |
| **symbol_specs** | `[exchange, symbol]` | `quote_currency`, `base_currency`, `min_trade_size`, etc. |

---

## 5. Execution & Error Logic
1.  **Validation:** Checks if the exchange/endpoint exists in JSON. If missing, it halts and reports via the `errors` list.
2.  **Mapping:** Universal symbol transformed via Regex.
3.  **Request:** URL constructed and sent via `aiohttp` with a 10s timeout.
4.  **Traversal:** The `_walk` engine follows JSON steps. If a step is broken, it halts the specific request and logs the exact missing node.
5.  **Normalization:** Numeric strings cast to floats; results packed into Multi-Index DataFrames.

---

## 6. Supported Exchanges (Initial Set)
*   **Crypto:** Binance, Bybit, OKX, Coinbase, Deribit, Gate.io, KuCoin, Crypto.com.
*   **TradFi:** Yahoo Finance (Forex/Stocks), AlphaVantage, Finnhub.

---

## 7. Next Steps
*   Populate the full `config.json` with all regex patterns and traversal paths.
*   Implement the `UniversalExchangeAPI` Python class as the core execution engine.
