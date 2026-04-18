"""Redis key and pub/sub channel namespacing — unprefixed keys are forbidden at call sites."""


def tenant_key(tenant_id: str, key_name: str) -> str:
    if not tenant_id or not key_name:
        raise ValueError("tenant_id and key_name are required")
    return f"{tenant_id}:{key_name}"


def tenant_channel(tenant_id: str, channel: str) -> str:
    if not tenant_id or not channel:
        raise ValueError("tenant_id and channel are required")
    return f"{tenant_id}:{channel}"


def bars_channel(tenant_id: str, symbol: str, interval: str) -> str:
    """Pub/sub channel for normalised OHLCV bars: ``{tenant_id}:bars:{symbol}:{interval}``.

    Every Redis channel name must start with ``tenant_id`` — never publish tenant data on a
    global unprefixed channel.
    """
    if not tenant_id or not symbol or not interval:
        raise ValueError("tenant_id, symbol, and interval are required")
    sym = symbol.strip()
    if not sym:
        raise ValueError("symbol must be non-empty")
    iv = interval.strip()
    if not iv:
        raise ValueError("interval must be non-empty")
    return f"{tenant_id}:bars:{sym}:{iv}"
