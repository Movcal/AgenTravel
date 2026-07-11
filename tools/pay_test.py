"""
Cliente de prueba x402: paga 0.10 USD₮0 en X Layer testnet y consume /ask.

Simula exactamente lo que hara un agente/cliente real contra AgenTravel:
  1. GET /ask -> recibe HTTP 402 con el challenge de pago
  2. Firma la autorizacion de pago con la wallet cliente (testnet)
  3. Reintenta con el header de pago -> el facilitador OKX liquida
  4. Recibe la recomendacion turistica

Uso:
  python tools/pay_test.py
  python tools/pay_test.py --city "Buenos Aires" --query "planes gratis" --date 2026-07-15

Requiere: testnet_client_wallet.json (wallet descartable) con USD₮0 de testnet
del faucet https://web3.okx.com/xlayer/faucet
"""
import argparse
import asyncio
import json
import os
import sys

from eth_account import Account

from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm.exact.register import register_exact_evm_client

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WALLET_FILE = os.path.join(BASE_DIR, "testnet_client_wallet.json")
SERVER      = os.environ.get("AGENTRAVEL_URL", "http://localhost:4021")


def load_wallet() -> Account:
    if not os.path.exists(WALLET_FILE):
        print(f"[ERROR] No existe {WALLET_FILE}. Crear la wallet de prueba primero.")
        sys.exit(1)
    with open(WALLET_FILE) as f:
        data = json.load(f)
    acct = Account.from_key(data["private_key"])
    print(f"Wallet cliente: {acct.address}")
    return acct


async def main(city: str, query: str, date: str | None):
    acct = load_wallet()

    client = x402Client()
    register_exact_evm_client(client, acct)

    params = {"city": city, "query": query}
    if date:
        params["date"] = date

    print(f"\nConsultando {SERVER}/ask (pagando 0.10 USD₮0 testnet via x402)...")
    async with x402HttpxClient(client, timeout=120) as http:
        resp = await http.get(f"{SERVER}/ask", params=params)
        print(f"HTTP {resp.status_code}")

        settle = resp.headers.get("payment-response")
        if settle:
            import base64
            info = json.loads(base64.b64decode(settle))
            print(f"\n--- LIQUIDACION DEL PAGO ---")
            print(json.dumps(info, indent=2, ensure_ascii=False)[:800])

        body = resp.json()
        print(f"\n--- RESPUESTA DEL AGENTE ---")
        out = body.get("response") if isinstance(body, dict) else None
        if out is None:
            out = json.dumps(body, indent=2, ensure_ascii=False)
        print(out[:1500])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Prueba de pago x402 contra AgenTravel")
    p.add_argument("--city",  default="Paris")
    p.add_argument("--query", default="What can I do tomorrow with a small budget?")
    p.add_argument("--date",  default=None)
    args = p.parse_args()
    asyncio.run(main(args.city, args.query, args.date))
