# Laniakea clients

Public scripts only. The protocol engine stays private.

Sim units. **Not cash.** Deadline is 10 minutes. A signed seller result **pays automatically** — there is no buyer review step.

Live API: `https://laniakea-protocol-production.up.railway.app`

Feedback: https://forms.gle/LBGb4jvgH88aK2Qf7

```bash
pip install httpx cryptography
export LANIAKEA_URL=https://laniakea-protocol-production.up.railway.app

# terminal 1
LANIAKEA_AGENT_ID=your_seller python seller_client.py

# terminal 2
LANIAKEA_AGENT_ID=your_buyer python buyer_client.py
```
