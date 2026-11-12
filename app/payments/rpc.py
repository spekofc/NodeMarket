"""Local wallet RPC client - stdlib only (urllib), no third-party deps.

Talks to a *local* Bitcoin Core node or monero-wallet-rpc over HTTP
JSON-RPC. Never called from the storefront path unless the admin enabled
it; failures are returned as values (never raised into a request), and
nothing about the responses is logged.

Security note: these endpoints hold (or can move) funds. Bind them to
127.0.0.1 and keep credentials in .env, never in the database.
"""

import base64
import json
import urllib.request

from ..config import settings


class RPCError(RuntimeError):
    pass


def _call(url: str, user: str, password: str, method: str,
          params: list | dict, timeout: float = 5.0):
    payload = json.dumps({"jsonrpc": "2.0", "id": "nodemarket",
                          "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data and data["error"] is not None:
        raise RPCError(str(data["error"]))
    return data.get("result")


def btc_call(method: str, params: list | None = None):
    """Bitcoin Core RPC. Returns result or raises RPCError."""
    return _call(settings.btc_rpc_url, settings.btc_rpc_user,
                 settings.btc_rpc_password, method, params or [])


def xmr_call(method: str, params: dict | None = None):
    """monero-wallet-rpc JSON-RPC. Returns result or raises RPCError."""
    return _call(settings.xmr_rpc_url, settings.xmr_rpc_user,
                 settings.xmr_rpc_password, method, params or {})


def btc_new_address(label: str) -> str:
    """Custodial-mode BTC address from the local node wallet."""
    return btc_call("getnewaddress", [label])


def xmr_new_address(label: str) -> str:
    """Per-order subaddress from the local monero-wallet-rpc."""
    result = xmr_call("create_address",
                      {"account_index": 0, "label": label})
    return result["address"]


def btc_sweep_all(destination: str) -> dict:
    """Move the entire BTC spendable balance to `destination`.

    Prefers `sendall` (Core >= 0.23); falls back to getbalance +
    sendtoaddress with fee subtraction for older nodes.
    """
    try:
        return btc_call("sendall", [{"": destination}])  # keyed "" = any wallet
    except RPCError:
        balance = float(btc_call("getbalance", ["*", 1]))  # confirmed, 1 conf
        if balance <= 0:
            raise RPCError("no confirmed balance to release")
        return btc_call("sendtoaddress",
                        [destination, balance, "NodeMarket escrow release",
                         "", True])


def xmr_sweep_all(destination: str) -> dict:
    """Move the entire unlocked XMR balance to `destination`."""
    return xmr_call("sweep_all", {"address": destination, "account_index": 0})
