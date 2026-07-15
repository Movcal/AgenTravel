# AgenTravel

Agente turístico autónomo con pagos x402 (X Layer / OKX).

Un viajero pregunta qué hacer en una ciudad en una fecha específica y el agente
responde con eventos y lugares **verificados en las páginas oficiales de cada
fuente** — no con conocimiento genérico de un LLM. Cobra 0.10 USDC por consulta.

## Diferenciador

- **Datos investigados, no inventados**: 20+ importers scrapean fuentes oficiales
  (Open Data de París, GCBA, teatros, estadios, museos). Cada registro guarda su
  fuente oficial y fecha de verificación, y el agente las cita en sus respuestas.
- **Archivo histórico**: los eventos pasados se archivan, no se borran. El endpoint
  `/stats` responde preguntas como "¿qué venue tiene más eventos en marzo?" que
  ningún chat puede responder.
- **Clima integrado**: pronóstico real (Open-Meteo) para la fecha consultada; el
  agente recomienda planes bajo techo si va a llover.

## Arquitectura: 3 agentes

| Agente | Archivo | Usa Claude | Función |
|---|---|---|---|
| Builder | `src/agents/builder.py` | Sí (~$0.13/ciudad, una vez) | Crea la base inicial de una ciudad nueva |
| Guardian | `src/agents/guardian.py` | No ($0) | Archiva eventos pasados y refresca importers (diario, 03:00) |
| Travel Agent | `api/server.py` | Sí (~$0.04/consulta) | El que ve el cliente: cobra $0.10 USDC vía x402 |

## Ciudades (6)

Buenos Aires, Santiago de Chile, Río de Janeiro, Madrid, París, New York City.
7,600+ eventos y 190 lugares verificados.

## Cómo correr

```bash
pip install -r requirements.txt

# Servidor API (puerto 4021)
python api/server.py

# Mantenimiento manual
python src/agents/guardian.py --no-refresh      # solo archivar
python src/agents/guardian.py --city Madrid     # refrescar una ciudad

# Scheduler (Guardian diario a las 03:00)
python scheduler.py
```

Variables en `.env` (no se commitea): `ANTHROPIC_API_KEY`, `PAY_TO_ADDRESS`,
`OKX_API_KEY`, `OKX_SECRET_KEY`, `OKX_PASSPHRASE`. Sin las keys OKX el servidor
arranca en modo sin pago (útil para desarrollo).

## Endpoints

- `GET /ask?city=Paris&query=...&date=2026-07-15` — consulta al agente (0.10 USDC vía x402)
- `POST /ask` — igual que el GET pero vía POST (los clientes x402 reenvían la petición pagada como POST); acepta los parámetros por body JSON (`{"city": ..., "query": ..., "date": ...}`) o query string
- `GET /stats?city=Madrid&month=03` — estadísticas históricas por ciudad/mes (gratis)
- `GET /cities` — ciudades disponibles
- `GET /health` — estado del servicio

## Estado (hackathon OKX.AI Genesis — deadline 17 jul 2026)

- [x] 3 agentes construidos y probados
- [x] 6 ciudades con datos verificados
- [x] x402 middleware listo (falta activar con keys OKX)
- [x] Bugs críticos pre-demo arreglados
- [ ] Keys OKX + prueba en testnet (`eip155:1952`)
- [ ] Deploy a VPS con HTTPS
- [ ] Registro como ASP en OKX.AI
- [ ] Post en X con demo (#OKXAI)
