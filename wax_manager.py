"""WAX wallet utility: balance, NFT inventory, and sweeping assets to a cold wallet.

Serialization is local (pyntelope); see wax_sniper.py for why the old
`eospy` / `abi_json_to_bin` approach no longer works on WAX.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Sequence

import pyntelope as nt
import requests
from loguru import logger
from pyntelope import types

from wax_sniper import DEFAULT_RPC, WaxError

ATOMIC_API = "https://wax.api.atomicassets.io/atomicassets/v1/assets"
WAX_PRECISION = 8
PAGE_SIZE = 1000          # AtomicAssets API maximum
NFT_BATCH = 100           # assets per transfer action (keeps tx under CPU/size limits)


def format_wax(amount: Decimal | str | float) -> str:
    """Format as an on-chain WAX asset string with exactly 8 decimals (truncating)."""
    q = Decimal(str(amount)).quantize(Decimal(1).scaleb(-WAX_PRECISION), rounding=ROUND_DOWN)
    if q <= 0:
        raise WaxError("amount must be greater than zero")
    return f"{q:.{WAX_PRECISION}f} WAX"


def chunked(seq: Sequence, size: int) -> list[list]:
    return [list(seq[i:i + size]) for i in range(0, len(seq), size)]


class WaxManager:
    def __init__(self, private_key: str | None, account: str, rpc_url: str = DEFAULT_RPC,
                 *, session: requests.Session | None = None):
        if not account:
            raise WaxError("account name is required")
        self.private_key = private_key
        self.account = account
        self.net = nt.WaxMainnet() if rpc_url == DEFAULT_RPC else nt.Net(host=rpc_url)
        self.http = session or requests.Session()

    # ── reads ────────────────────────────────────────────────────────────
    def get_wax_balance(self) -> Decimal:
        """Liquid WAX balance from the eosio.token `accounts` table."""
        rows = self.net.get_table_rows(
            code="eosio.token", table="accounts", scope=self.account,
        )
        for row in rows:
            qty, sym = row["balance"].split()
            if sym == "WAX":
                return Decimal(qty)
        return Decimal(0)

    def get_nfts(self, collection: str | None = None) -> list[str]:
        """Every AtomicAssets NFT the account owns (all pages, not just the first)."""
        ids: list[str] = []
        page = 1
        while True:
            params = {"owner": self.account, "limit": PAGE_SIZE, "page": page,
                      "order": "asc", "sort": "asset_id"}
            if collection:
                params["collection_name"] = collection
            resp = self.http.get(ATOMIC_API, params=params, timeout=20)
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success"):
                raise WaxError(f"AtomicAssets API error: {body}")
            batch = [a["asset_id"] for a in body.get("data", [])]
            ids.extend(batch)
            if len(batch) < PAGE_SIZE:
                return ids
            page += 1

    # ── writes ───────────────────────────────────────────────────────────
    def _send(self, actions: list[nt.Action], *, dry_run: bool) -> str | None:
        if not self.private_key:
            raise WaxError("private key is required to send transactions")
        linked = nt.Transaction(actions=actions).link(net=self.net)
        if dry_run:
            logger.info(f"[dry-run] {len(actions)} action(s) serialized OK — not sent")
            return None
        resp = linked.sign(key=self.private_key).send()
        tx_id = resp.get("transaction_id") if isinstance(resp, dict) else None
        if not tx_id:
            raise WaxError(f"transaction rejected: {resp}")
        logger.success(f"tx {tx_id}")
        return tx_id

    def _auth(self) -> list[nt.Authorization]:
        return [nt.Authorization(actor=self.account, permission="active")]

    def transfer_wax(self, to: str, amount: Decimal | str | float, memo: str = "",
                     *, dry_run: bool = False) -> str | None:
        quantity = format_wax(amount)
        logger.info(f"send {quantity} -> {to}")
        action = nt.Action(
            account="eosio.token", name="transfer", authorization=self._auth(),
            data=[
                nt.Data(name="from", value=types.Name(self.account)),
                nt.Data(name="to", value=types.Name(to)),
                nt.Data(name="quantity", value=types.Asset(quantity)),
                nt.Data(name="memo", value=types.String(memo)),
            ],
        )
        return self._send([action], dry_run=dry_run)

    def transfer_nfts(self, to: str, asset_ids: Sequence[str | int], memo: str = "",
                      *, dry_run: bool = False) -> list[str | None]:
        """Send NFTs in batches so big wallets don't blow the tx size/CPU limit."""
        if not asset_ids:
            return []
        results = []
        batches = chunked(list(asset_ids), NFT_BATCH)
        for i, batch in enumerate(batches, 1):
            logger.info(f"NFT batch {i}/{len(batches)}: {len(batch)} assets -> {to}")
            action = nt.Action(
                account="atomicassets", name="transfer", authorization=self._auth(),
                data=[
                    nt.Data(name="from", value=types.Name(self.account)),
                    nt.Data(name="to", value=types.Name(to)),
                    nt.Data(name="asset_ids", value=types.Array(
                        values=[types.Uint64(int(a)) for a in batch], type_=types.Uint64)),
                    nt.Data(name="memo", value=types.String(memo)),
                ],
            )
            results.append(self._send([action], dry_run=dry_run))
        return results


def main() -> int:
    import config

    try:
        mgr = WaxManager(config.ACC_PK, config.CLAIMER,
                         getattr(config, "RPC_URL", DEFAULT_RPC))
        destination = config.COLD_WALLET
    except AttributeError as exc:
        logger.error(f"config incomplete: {exc}. See config_example.py")
        return 1
    if destination == mgr.account:
        logger.error("COLD_WALLET must differ from the source account")
        return 1

    print(f"Source: {mgr.account}  ->  Cold wallet: {destination}")
    print("1: Send WAX")
    print("2: Sweep all NFTs")
    choice = input("Select: ").strip()

    try:
        if choice == "1":
            bal = mgr.get_wax_balance()
            logger.info(f"balance: {bal} WAX")
            if bal <= 0:
                return 0
            amount = Decimal(input(f"Amount to send (max {bal}): ").strip())
            if amount > bal:
                logger.error("amount exceeds balance")
                return 1
            mgr.transfer_wax(destination, amount, dry_run=True)
            if input("Send for real? Type 'yes': ").strip().lower() == "yes":
                mgr.transfer_wax(destination, amount)
        elif choice == "2":
            nfts = mgr.get_nfts()
            logger.info(f"found {len(nfts)} NFTs")
            if not nfts:
                return 0
            mgr.transfer_nfts(destination, nfts, dry_run=True)
            if input(f"Send ALL {len(nfts)} NFTs for real? Type 'yes': ").strip().lower() == "yes":
                mgr.transfer_nfts(destination, nfts)
        else:
            print("Invalid choice")
            return 1
    except (WaxError, requests.RequestException) as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
