#!/usr/bin/env python3
"""Minimal external seller: register, faucet, stake, poll jobs, deliver.

Units are simulated. This is not cash.
Usage:
  LANIAKEA_URL=https://your-host python seller_client.py
"""
from __future__ import annotations

import json
import os
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

URL = os.environ.get("LANIAKEA_URL", "http://127.0.0.1:8000").rstrip("/")
AGENT_ID = os.environ.get("LANIAKEA_AGENT_ID", "seller_delta")
TASK = os.environ.get("LANIAKEA_TASK", "copywriting")
PRICE = float(os.environ.get("LANIAKEA_PRICE", "0.5"))
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
        "capabilities": [{"task_type": TASK, "cost_per_unit": PRICE, "unit": "execution"}],
    }
    r = httpx.post(f"{URL}/agents/register", json={**body, "signature": sign(body)}, timeout=20)
    r.raise_for_status()
    faucet = {"agent_id": AGENT_ID, "amount": 25.0}
    httpx.post(f"{URL}/faucet", json={**faucet, "signature": sign(faucet)}, timeout=20).raise_for_status()
    stake = {"agent_id": AGENT_ID, "amount": 10.0}
    httpx.post(f"{URL}/stake", json={**stake, "signature": sign(stake)}, timeout=20).raise_for_status()
    print("listed. polling /jobs …")
    while True:
        jobs = httpx.get(f"{URL}/jobs", params={"seller_id": AGENT_ID}, timeout=20).json()
        for job in jobs:
            tx = job["transaction_id"]
            output = f"completed {TASK} for {job['buyer_agent_id']}"
            result_body = {
                "transaction_id": tx,
                "seller_agent_id": AGENT_ID,
                "status": "success",
                "output_data": output,
            }
            try:
                resp = httpx.post(
                    f"{URL}/jobs/{tx}/result",
                    json={
                        "seller_agent_id": AGENT_ID,
                        "status": "success",
                        "output_data": output,
                        "signature": sign(result_body),
                    },
                    timeout=20,
                )
                print(f"result POST {tx} -> {resp.status_code} (receipt, not settlement)")
            except httpx.HTTPError as exc:
                print(f"result POST {tx} unclear ({exc}); confirming host state")
            last = None
            for _ in range(40):
                last = confirm(URL, tx)
                if last["settled"]:
                    print(
                        f"settled {tx} escrow={last['escrow_state']} conserved={last['conserved']}"
                    )
                    print(FEEDBACK)
                    break
                time.sleep(0.5)
            else:
                print(f"unconfirmed {tx} escrow={None if not last else last.get('escrow_state')} conserved={None if not last else last.get('conserved')}")
                print(FEEDBACK)
        time.sleep(2)


if __name__ == "__main__":
    main()
