# WAX Blockchain NFT Sniper

A direct blockchain interaction tool designed to claim NFT drops from AtomicHub and NeftyBlocks contracts on the WAX network.

### Key Features
* **Direct Node Interaction:** Uses `eospy` to communicate directly with WAX RPC nodes, bypassing slow UI interfaces.
* **ABI Serialization:** Handles local packing of JSON arguments into binary format (`abi_json_to_bin`) for transaction signing.
* **Smart Contract Support:** Supports multiple claim methods:
  * Public Drops
  * Whitelisted Drops (WL)
  * Proof-of-Ownership Drops
* **Multi-Platform:** Unified logic for both AtomicAssets and NeftyBlocks standards.

### Tech Stack
* Python 3.9+
* Eospy (EOSIO SDK)
* Cryptography (ECDSA signing)

### 📦 Wallet Manager (`wax_manager.py`)
Additional utility to manage assets.
* **Pure RPC Balance Check:** Fetches token balance directly from `eosio.token` contract.
* **NFT Indexer API:** Uses AtomicAssets API to discover owned NFTs.

* **Bulk Transfers:** Supports sweeping tokens and NFTs to a cold wallet.
