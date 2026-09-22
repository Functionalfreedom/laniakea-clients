#!/usr/bin/env python3
"""Minimal external buyer: register, faucet, discover, handshake, wait for settle.

Units are simulated. This is not cash.
Run a seller in another terminal first (or LANIAKEA_SELLER=an already-listed id).

Usage:
  LANIAKEA_URL=https://laniakea-protocol-production.up.railway.app python buyer_client.py
"""
from __future__ import annotations

import json
import os
import time
import uuid

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

URL = os.environ.get("LANIAKEA_URL", "https://laniakea-protocol-production.up.railway.app").rstrip("/")
AGENT_ID = os.environ.get("LANIAKEA_AGENT_ID", "buyer_epsilon")
TASK = os.environ.get("LANIAKEA_TASK", "copywriting")
SELLER = os.environ.get("LANIAKEA_SELLER", "")
BRIEF = os.environ.get("LANIAKEA_BRIEF", "one paragraph, any topic")
FEEDBACK = "Trouble or feedback? https://forms.gle/LBGb4jvgH88aK2Qf7"


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def main() -> None:
    private = Ed25519PrivateKey.generate()
    pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    priv_hex = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    print(f"agent {AGENT_ID}")
    print(f"public_key {pub}")

    def sign(payload: dict) -> str:
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
        return key.sign(canonical(payload)).hex()

    body = {
        "agent_id": AGENT_ID,
        "public_key": pub,
        "endpoint": "external",
        "capabilities": [],
    }
    r = httpx.post(f"{URL}/agents/register", json={**body, "signature": sign(body)}, timeout=20)
    r.raise_for_status()
    faucet = {"agent_id": AGENT_ID, "amount": 25.0}
    httpx.post(f"{URL}/faucet", json={**faucet, "signature": sign(faucet)}, timeout=20).raise_for_status()

    offers = httpx.get(f"{URL}/discover/tasks/{TASK}", timeout=20).json()
    seller_id = SELLER
    cost = 0.5
    if seller_id:
        match = next((o for o in offers if o["agent_id"] == seller_id), None)
        if match:
            cost = float(match["cost"])
    elif offers:
        seller_id = offers[0]["agent_id"]
        cost = float(offers[0]["cost"])
    else:
        raise SystemExit(f"no listed seller for {TASK}. start seller_client.py first.")

    print(f"hiring {seller_id} cost={cost}")
    tx_id = "tx_" + uuid.uuid4().hex[:12]
    hs = {
        "transaction_id": tx_id,
        "buyer_agent_id": AGENT_ID,
        "seller_agent_id": seller_id,
        "action_type": "task",
        "payload": {"action": TASK, "parameters": {"brief": BRIEF}},
        "escrow_amount": cost,
        "verification_type": "ed25519",
        "timestamp": time.time(),
        "status": "pending",
        "escrow_state": None,
    }
    signed = {k: v for k, v in hs.items() if k not in ("signature", "status", "escrow_state")}
    hs["signature"] = sign(signed)
    posted = httpx.post(f"{URL}/handshake", json=hs, timeout=20)
    posted.raise_for_status()
    print(f"held {posted.json()}")

    deadline = time.time() + 90
    while time.time() < deadline:
        st = httpx.get(f"{URL}/transaction/{tx_id}", timeout=20).json()
        state = (st.get("escrow") or {}).get("state")
        print(f"escrow={state}")
        if state in ("released_to_seller", "refunded_to_buyer"):
            print(json.dumps(st, indent=2))
            print(FEEDBACK)
            return
        time.sleep(2)
    print(FEEDBACK)
    raise SystemExit("timed out waiting for settlement")


if __name__ == "__main__":
    main()
