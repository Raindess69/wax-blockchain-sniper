"""Copy to config.py (git-ignored) and fill in. NEVER commit real keys.

Prefer environment variables for secrets; this file reads them if present.
"""
import os

# Account + key (use a dedicated low-balance hot wallet)
CLAIMER = os.getenv("WAX_ACCOUNT", "youraccount1")
ACC_PK = os.getenv("WAX_PRIVATE_KEY", "")          # PVT_K1_... or legacy 5K... WIF

# Optional: your own node for lower latency (default: Greymass public RPC)
RPC_URL = os.getenv("WAX_RPC", "https://wax.greymass.com")

# ── wax_sniper.py ──
DROP_ID = 123456            # drop id from the AtomicHub / NeftyBlocks URL
AMOUNT = 1                  # how many to claim
CURRENCY = "8,WAX"          # NeftyBlocks only: precision,symbol of the price token
COUNTRY = "US"
COOLDOWN = 1.0              # seconds between attempts
ASSET_IDS = []              # NeftyBlocks proof drops: asset ids that satisfy the proof

# ── wax_manager.py ──
COLD_WALLET = "yourcold1111"
