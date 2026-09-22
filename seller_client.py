#!/usr/bin/env python3
"""Minimal external seller: register, faucet, stake, poll jobs, deliver.

Units are simulated. This is not cash.
Usage:
  LANIAKEA_URL=https://laniakea-protocol-production.up.railway.app python seller_client.py
"""
from __future__ import annotations

import json
import os
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

URL = os.environ.get("LANIAKEA_URL", "https://laniakea-protocol-production.up.railway.app").rstrip("/")
AGENT_ID = os.environ.get("LANIAKEA_AGENT_ID", "seller_delta")
TASK = os.environ.get("LANIAKEA_TASK", "copywriting")
PRICE = float(os.environ.get("LANIAKEA_PRICE", "0.5"))
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
            print(f"delivered {tx} -> {resp.status_code}")
            for _ in range(40):
                st = httpx.get(f"{URL}/transaction/{tx}", timeout=20).json()
                state = (st.get("escrow") or {}).get("state")
                if state in ("released_to_seller", "refunded_to_buyer"):
                    print(f"settled {tx} escrow={state}")
                    print(FEEDBACK)
                    break
                time.sleep(0.5)
            else:
                print(FEEDBACK)
        time.sleep(2)


if __name__ == "__main__":
    main()
