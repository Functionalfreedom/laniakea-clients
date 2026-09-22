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

URL = os.environ.get("LANIAKEA_URL", "http://127.0.0.1:8000").rstrip("/")
AGENT_ID = os.environ.get("LANIAKEA_AGENT_ID", "buyer_epsilon")
TASK = os.environ.get("LANIAKEA_TASK", "copywriting")
SELLER = os.environ.get("LANIAKEA_SELLER", "")
BRIEF = os.environ.get("LANIAKEA_BRIEF", "one paragraph, any topic")
FEEDBACK = "Trouble or feedback? https://forms.gle/LBGb4jvgH88aK2Qf7"
TERMINAL = ("released_to_seller", "refunded_to_buyer")


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def confirm(url: str, tx_id: str, *, timeout: float = 20) -> dict:
    """Read current escrow + conservation. A POST receipt is not settlement."""
    tr = httpx.get(f"{url}/transaction/{tx_id}", timeout=timeout)
    cons_r = httpx.get(f"{url}/conservation", timeout=timeout)
    cons = cons_r.json() if cons_r.status_code == 200 else {}
    conserved = bool(cons.get("conserved"))
    if tr.status_code != 200:
        return {
            "transaction_id": tx_id,
            "escrow_state": None,
            "conserved": conserved,
            "settled": False,
            "unknown": True,
            "http": tr.status_code,
        }
    st = tr.json()
    state = (st.get("escrow") or {}).get("state")
    return {
        "transaction_id": tx_id,
        "escrow_state": state,
        "conserved": conserved,
        "settled": state in TERMINAL and conserved,
        "unknown": False,
        "http": 200,
        "transaction": st,
        "conservation": cons,
    }


def handshake_tx_id(response_json: dict, local_id: str) -> str:
    """Authoritative id is the 200 body. Local request id is a hint only."""
    remote = (response_json or {}).get("transaction_id")
    if not remote:
        raise ValueError("handshake 200 missing transaction_id")
    return remote


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
    local_id = "tx_" + uuid.uuid4().hex
    hs = {
        "transaction_id": local_id,
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
    try:
        posted = httpx.post(f"{URL}/handshake", json=hs, timeout=20)
        posted.raise_for_status()
        tx_id = handshake_tx_id(posted.json(), local_id)
        if tx_id != local_id:
            print(f"using response transaction_id {tx_id} (request had {local_id})")
        print(f"receipt {posted.json()}")
    except (httpx.HTTPError, ValueError) as exc:
        print(f"handshake unclear ({exc}); confirming host with request id {local_id}")
        tx_id = local_id

    first = confirm(URL, tx_id)
    if first["unknown"] or first["escrow_state"] not in ("held",) + TERMINAL:
        print(f"unknown: no fresh escrow for {tx_id} (http={first.get('http')} state={first.get('escrow_state')})")
        print(FEEDBACK)
        raise SystemExit("handshake not confirmed on host")
    print(f"held {tx_id} escrow={first['escrow_state']} conserved={first['conserved']}")

    deadline = time.time() + 200
    last = first
    while time.time() < deadline:
        last = confirm(URL, tx_id)
        print(f"escrow={last.get('escrow_state')} conserved={last.get('conserved')} settled={last.get('settled')}")
        if last["settled"]:
            print(json.dumps({"transaction": last.get("transaction"), "conservation": last.get("conservation")}, indent=2))
            print(FEEDBACK)
            return
        time.sleep(2)
    print(f"unconfirmed {tx_id} last_state={last.get('escrow_state')} conserved={last.get('conserved')}")
    print(FEEDBACK)
    raise SystemExit("timed out waiting for confirmed settlement")


if __name__ == "__main__":
    main()
