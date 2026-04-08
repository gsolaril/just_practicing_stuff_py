import os, sys, asyncio, aiohttp, json, re, pandas as pd
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any, Union
from loguru import logger

# --- Logger Configuration ---
logger.remove()
FORMAT = "[<level>{time:HH:mm:ss.SSS!UTC} | {module}.{function} @ L{line}</level>] {message}"
logger.add(sys.stderr, format=FORMAT, level="INFO")

def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert object/string columns to numeric where possible; keep original values when conversion fails."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if s.dtype != object and not pd.api.types.is_string_dtype(s.dtype):
            continue
        converted = pd.to_numeric(s, errors="coerce")
        out[col] = converted.fillna(s)
    return out


def _digits_from_point_size(v: Any) -> Any:
    """
    Best-effort conversion of a price increment / tick size into display digits.
    - If v looks like an integer precision (e.g. 8), return int(v)
    - If v looks like a tick size (e.g. 0.0001), return number of decimal places (4)
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        d = Decimal(str(v)).normalize()
    except (InvalidOperation, ValueError):
        return None

    # If it's a whole number, treat as already-a-digit count.
    if d == d.to_integral_value():
        try:
            return int(d)
        except Exception:
            return None

    # Otherwise treat it as a tick size and count decimals.
    s = format(d, "f")
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1].rstrip("0"))


class APIDS:
    CONFIG = {}

    @classmethod
    def load_config(cls, file_path: str):
        with open(file_path, 'r') as f:
            cls.CONFIG = json.load(f)
        logger.info(f"Loaded config from {file_path}")

    @staticmethod
    def _map_symbol(exchange_cfg: Dict, universal_symbol: str) -> str:
        mapping = exchange_cfg.get("symbol_mapping")
        if not mapping or "/" not in universal_symbol:
            return universal_symbol
        return re.sub(mapping["pattern"], mapping["replacement"], universal_symbol)

    @staticmethod
    def _walk(data: Any, path_list: List[Union[str, int]], field_name: str = "Unknown") -> Any:
        if path_list is None or path_list == []: return data
        curr = data
        for i, step in enumerate(path_list):
            try:
                if step == "*FIRST_KEY*":
                    curr = curr[list(curr.keys())[0]]
                else:
                    curr = curr[step]
            except Exception:
                raise ValueError(f"Step '{step}' failed for {field_name}")
        return curr

    @classmethod
    async def _execute(
        cls,
        session: aiohttp.ClientSession,
        exchange: str,
        endpoint_key: str,
        universal_symbol: str | None,
        retries: int = 3,
        backoff: float = 1.5,
        **kwargs,
    ):
        try:
            cfg = cls.CONFIG[exchange]
            ep = cfg[endpoint_key]
            target_symbol = cls._map_symbol(cfg, universal_symbol) if universal_symbol is not None else None
            
            if "{symbol}" in ep["endpoint_path"] and target_symbol is None:
                return False, None, "symbol is required for this endpoint"

            url = cfg["base_url"] + ep["endpoint_path"].replace("{symbol}", target_symbol or "")
            
            params = {}
            for k, v in ep.get("args", {}).items():
                if v == "symbol":
                    if target_symbol is None:
                        # For bulk symbol_specs, allow an exchange-specific default (e.g. Bybit category=spot, Deribit currency=BTC).
                        if endpoint_key == "symbol_specs" and "default_symbol" in ep:
                            params[k] = ep.get("default_symbol")
                    else:
                        params[k] = target_symbol
                elif v == "interval": params[k] = kwargs.get("interval", "1h")
                elif v == "limit": params[k] = kwargs.get("limit", 100)
                elif v == "key": params[k] = cfg.get("key", "")
                else: params[k] = v

            for attempt in range(retries):
                try:
                    async with session.request(ep["method"], url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            raw = await resp.json()
                            mapping = ep["mapping"]

                            if "root" in mapping:
                                iv = kwargs.get("interval", "1h")
                                r_path = [
                                    s.replace("*INTERVAL*", str(iv)) if isinstance(s, str) else s
                                    for s in mapping["root"]
                                ]
                                root = cls._walk(raw, r_path, "root")
                                
                                # Iterate Keys logic (Aggregators)
                                if isinstance(root, dict) and mapping.get("timestamp") == ["*ITERATE_KEYS*"]:
                                    data = []
                                    for ts, val in root.items():
                                        row = {"timestamp": ts}
                                        row.update({k: cls._walk(val, v, k) for k, v in mapping.items() if k not in ["root", "timestamp"]})
                                        data.append(row)
                                    return True, data, None

                                # Dict roots: { "PAIR": {spec}, ... } → one-key dicts per pair so *FIRST_KEY* paths match Kraken-style mappings.
                                if isinstance(root, dict):
                                    vals = list(root.values())
                                    if vals and all(isinstance(v, dict) for v in vals):
                                        root = [{k: v} for k, v in root.items()]
                                    elif mapping.get("timestamp") != ["*ITERATE_KEYS*"]:
                                        root = [root]

                                return True, [{k: cls._walk(item, v, k) for k, v in mapping.items() if k != "root"} for item in root], None
                            
                            return True, {k: cls._walk(raw, v, k) for k, v in mapping.items()}, None
                        
                        elif resp.status in [429, 500, 502, 503, 504]:
                            wait = backoff * (attempt + 1)
                            logger.warning(f"{exchange} {resp.status} - Retrying in {wait}s...")
                            await asyncio.sleep(wait)
                        else:
                            return False, None, f"HTTP {resp.status}"
                except Exception as e:
                    if attempt == retries - 1: raise e
                    await asyncio.sleep(backoff * (attempt + 1))

        except Exception as e:
            return False, None, str(e)

    @classmethod
    async def fetch(
        cls,
        session: aiohttp.ClientSession,
        exchange: str,
        endpoint: str,
        symbol: str | None = None,
        **kwargs,
    ) -> Dict:
        success, data, err = await cls._execute(session, exchange, endpoint, symbol, **kwargs)
        res = {"status": success, "output": pd.DataFrame(), "errors": []}
        
        if not success:
            res["errors"].append({"exchange": exchange, "symbol": symbol, "error": err})
            return res

        try:
            df = _coerce_numeric_columns(pd.DataFrame(data if isinstance(data, list) else [data]))

            # For bulk symbol_specs, the returned payload should include a per-row 'symbol' (or similar) field.
            # In that case, we do NOT want to overwrite it with a single input symbol.
            df["exchange"] = exchange
            if symbol is not None:
                df["symbol"] = symbol

            if endpoint == "symbol_specs":
                if "digits" not in df.columns:
                    if "point_size" in df.columns:
                        df["digits"] = df["point_size"].apply(_digits_from_point_size)
                    else:
                        df["digits"] = None
                else:
                    df["digits"] = df["digits"].apply(_digits_from_point_size)
            
            if endpoint == "order_book":
                def _book_side(rows, p_col: str, v_col: str) -> pd.DataFrame:
                    pairs = []
                    for r in rows or []:
                        if r and len(r) >= 2:
                            pairs.append([float(r[0]), float(r[1])])
                    return pd.DataFrame(pairs, columns=[p_col, v_col]).astype(float)

                b_df = _book_side(data.get("bids"), "bid_p", "bid_v")
                a_df = _book_side(data.get("asks"), "ask_p", "ask_v")
                df = pd.concat([a_df, b_df], axis=1)
                df["exchange"] = exchange
                df["symbol"] = symbol
                df["level"] = df.index
                res["output"] = df.set_index(['exchange', 'symbol', 'level'])
            elif "timestamp" in df.columns:
                res["output"] = df.set_index(['exchange', 'symbol', 'timestamp'])
            else:
                # If bulk symbol_specs did not return 'symbol', fall back to a single-row index.
                if "symbol" in df.columns:
                    res["output"] = df.set_index(["exchange", "symbol"])
                else:
                    res["output"] = df.set_index(["exchange"])
            
            logger.success(f"Fetched {exchange} {symbol}")
            return res
        except Exception as e:
            res["status"] = False
            res["errors"].append({"exchange": exchange, "error": str(e)})
            return res

# --- Main Entry ---
async def main():
    APIDS.load_config("./apids.json")
    async with aiohttp.ClientSession() as session:
        tasks = [
            APIDS.fetch(session, "Binance", "current_price", "BTC/USDT"),
        ]
        results = await asyncio.gather(*tasks)
        frames = [r["output"] for r in results if r["status"]]
        if not frames:
            print("\n--- No successful fetches ---")
            for r in results:
                for err in r.get("errors", []):
                    print(err)
            return
        print("\n--- Stacked Data ---\n", pd.concat(frames))

if __name__ == "__main__":
    asyncio.run(main())
