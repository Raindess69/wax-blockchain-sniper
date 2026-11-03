"""WAX NFT drop claimer for AtomicHub (atomicdropsx) and NeftyBlocks (neftyblocksd).

Transactions are serialized locally with `pyntelope`, which fetches each
contract's ABI through the still-supported `get_abi` endpoint. The legacy
server-side `abi_json_to_bin` path the old `eospy` code relied on has been
disabled on modern WAX nodes, so that approach no longer works at all.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import pyntelope as nt
from loguru import logger
from pyntelope import types

DEFAULT_RPC = "https://wax.greymass.com"

# (contract, action, needs asset_ids proof). Field schemas differ between the
# two platforms; the builder below sends exactly what each ABI declares.
MODES: dict[int, tuple[str, str, bool]] = {
    1: ("atomicdropsx", "claimdrop", False),    # AtomicHub, public
    2: ("atomicdropsx", "claimdropwl", False),  # AtomicHub, whitelist
    3: ("neftyblocksd", "claimdrop", False),    # NeftyBlocks, public
    4: ("neftyblocksd", "claimdropwl", False),  # NeftyBlocks, whitelist
    5: ("neftyblocksd", "claimwproof", True),   # NeftyBlocks, proof-of-ownership
}


class WaxError(RuntimeError):
    pass


@dataclass
class ClaimSpec:
    drop_id: int
    amount: int = 1
    currency: str = "8,WAX"       # precision,symbol as declared by the token
    country: str = "US"
    referrer: str = ""


class WaxClaimer:
    def __init__(self, private_key: str, account: str, rpc_url: str = DEFAULT_RPC):
        if not private_key:
            raise WaxError("private key is required")
        if not account:
            raise WaxError("account name is required")
        self.private_key = private_key
        self.account = account
        self.net = nt.WaxMainnet() if rpc_url == DEFAULT_RPC else nt.Net(host=rpc_url)

    def _auth(self) -> list[nt.Authorization]:
        return [nt.Authorization(actor=self.account, permission="active")]

    def _claim_data(
        self, contract: str, action: str, spec: ClaimSpec,
        asset_ids: Sequence[int] | None,
    ) -> list[nt.Data]:
        """Build the typed action data matching each contract's real ABI."""
        median = types.Uint64(0)  # intended_delphi_median: 0 for free / non-priced drops

        if contract == "atomicdropsx":
            # claim_amount is uint64; no currency field on Atomic.
            data = [
                nt.Data(name="claimer", value=types.Name(self.account)),
                nt.Data(name="drop_id", value=types.Uint64(spec.drop_id)),
                nt.Data(name="claim_amount", value=types.Uint64(spec.amount)),
                nt.Data(name="intended_delphi_median", value=median),
                nt.Data(name="referrer", value=types.String(spec.referrer)),
                nt.Data(name="country", value=types.String(spec.country)),
            ]
            return data

        # neftyblocksd: amount is uint32, plus currency + referrer_account.
        data = [
            nt.Data(name="claimer", value=types.Name(self.account)),
            nt.Data(name="drop_id", value=types.Uint64(spec.drop_id)),
            nt.Data(name="amount", value=types.Uint32(spec.amount)),
            nt.Data(name="intended_delphi_median", value=median),
            nt.Data(name="referrer", value=types.String(spec.referrer)),
        ]
        if action == "claimwproof":
            ids = [types.Uint64(int(a)) for a in (asset_ids or [])]
            if not ids:
                raise WaxError("claimwproof requires at least one asset id for proof")
            data.append(nt.Data(name="asset_ids", value=types.Array(values=ids, type_=types.Uint64)))
        data.extend([
            nt.Data(name="country", value=types.String(spec.country)),
            nt.Data(name="currency", value=types.Symbol(spec.currency)),
            nt.Data(name="referrer_account", value=types.Name(spec.referrer or self.account)),
        ])
        return data

    def claim_once(
        self, mode: int, spec: ClaimSpec,
        asset_ids: Sequence[int] | None = None,
        *, dry_run: bool = False,
    ) -> bool:
        if mode not in MODES:
            raise WaxError(f"invalid mode {mode}; choose one of {sorted(MODES)}")
        contract, action, needs_proof = MODES[mode]
        if needs_proof and not asset_ids:
            raise WaxError(f"mode {mode} ({contract}/{action}) needs asset_ids")

        act = nt.Action(
            account=contract,
            name=action,
            data=self._claim_data(contract, action, spec, asset_ids),
            authorization=self._auth(),
        )
        tx = nt.Transaction(actions=[act])

        if dry_run:
            # Linking fetches the ABI and the ref block, then serializes locally —
            # proves the action is valid without broadcasting anything.
            tx.link(net=self.net)
            logger.info(f"[dry-run] {contract}/{action} drop={spec.drop_id} serialized OK")
            return True

        linked = tx.link(net=self.net)
        signed = linked.sign(key=self.private_key)
        resp = signed.send()
        tx_id = resp.get("transaction_id") if isinstance(resp, dict) else None
        if tx_id:
            logger.success(f"claimed! tx {tx_id}")
            return True
        logger.error(f"claim rejected: {resp}")
        return False

    def snipe(
        self, mode: int, spec: ClaimSpec,
        asset_ids: Sequence[int] | None = None,
        *, cooldown: float = 1.0, max_attempts: int = 0,
    ) -> bool:
        """Retry until a claim succeeds. max_attempts=0 means unlimited."""
        attempt = 0
        while True:
            attempt += 1
            try:
                if self.claim_once(mode, spec, asset_ids):
                    return True
            except WaxError:
                raise  # config errors won't fix themselves by retrying
            except Exception as exc:  # transient network / node / timing errors
                logger.debug(f"attempt {attempt} failed: {exc}")
            if max_attempts and attempt >= max_attempts:
                logger.warning(f"gave up after {attempt} attempts")
                return False
            time.sleep(cooldown)


def main() -> int:
    import config

    try:
        claimer = WaxClaimer(
            private_key=config.ACC_PK,
            account=config.CLAIMER,
            rpc_url=getattr(config, "RPC_URL", DEFAULT_RPC),
        )
        spec = ClaimSpec(
            drop_id=int(config.DROP_ID),
            amount=int(getattr(config, "AMOUNT", 1)),
            currency=getattr(config, "CURRENCY", "8,WAX"),
            country=getattr(config, "COUNTRY", "US"),
        )
    except (AttributeError, ValueError) as exc:
        logger.error(f"config incomplete: {exc}. See config_example.py")
        return 1

    print("Modes:")
    for m, (contract, action, _) in MODES.items():
        print(f"  {m}: {contract}/{action}")
    try:
        mode = int(input("Choose mode: "))
    except ValueError:
        logger.error("mode must be a number")
        return 1

    asset_ids = getattr(config, "ASSET_IDS", None)
    cooldown = float(getattr(config, "COOLDOWN", 1.0))

    claimer.claim_once(mode, spec, asset_ids, dry_run=True)
    if input("Start sniping for real? Type 'yes': ").strip().lower() != "yes":
        logger.info("aborted")
        return 0
    ok = claimer.snipe(mode, spec, asset_ids, cooldown=cooldown)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
