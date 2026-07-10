# Arquitectura del Sistema AgenTravel

## Diagrama General

```
Fuentes externas
       │
       ▼
┌─────────────────────┐
│  Agente Constructor │  (Builder)
└─────────────────────┘
       │
       ▼
  Base de datos
       ▲
       │
┌─────────────────────┐
│  Agente Guardian    │  (Maintenance)
└─────────────────────┘
       ▲
       │
  Scheduler (cron)

       │

Usuario
  │
  ▼
Pago USDC (x402 / APP Protocol)
  │
  ▼
┌─────────────────────┐
│  Agente Turistico   │  (Travel Agent) ← el que ve el cliente
└─────────────────────┘
  │
  ▼
Respuesta personalizada
```

## Componentes del Sistema

### Agentes inteligentes

#### 1. Agente Constructor (Builder)
- **Funcion**: crear la base inicial ciudad por ciudad
- **Cuando se usa**: al inicio y cuando se agregan nuevas ciudades
- **Entrada**: "Construye la base turistica de Buenos Aires"
- **Salida**: lugares permanentes, eventos, fuentes, horarios, precios, nivel de confianza
- **Prompt**: ver `prompts/agent_builder.md`

#### 2. Agente Guardian (Maintenance)
- **Funcion**: mantener la informacion viva y confiable
- **Cuando se usa**: continuamente via Scheduler
- **Tareas**: revisar horarios, detectar cambios, confirmar eventos, archivar vencidos
- **Prompt**: ver `prompts/agent_guardian.md`

#### 3. Agente Turistico (Travel Agent)
- **Funcion**: el que ve el cliente, genera ingresos
- **Precio**: 0.10 USDC por consulta via x402
- **Proceso**: recibe pregunta → verifica pago → busca en base → consulta clima → genera guia
- **Prompt**: ver `prompts/agent_travel.md`

### Componentes de soporte (no son agentes)

#### 4. Scheduler (orquestador)
- No es un agente inteligente, es un programador (cron)
- Decide: que ciudad revisar, que fuente revisar, cuando actualizar, que archivar
- Ejemplo de tarea diaria:
  - Revisar museos de Santiago
  - Revisar eventos de Buenos Aires
  - Archivar conciertos terminados

#### 5. Base de datos
- Vive el conocimiento: ciudades, lugares, eventos, fuentes, historial, estados
- Dos tipos de datos: permanentes (cambian poco) y temporales (eventos con ciclo de vida)

#### 6. Sistema de pagos (x402 / APP Protocol)
- Detecta pago 402
- Valida USDC en X Layer
- Autoriza la consulta al Travel Agent
- Implementado con: `okxweb3-app-x402` + FastAPI middleware

## Flujo de una consulta de usuario

```
1. Usuario llama: GET /travel?city=Paris&dates=2026-08-15
2. Middleware x402 intercepta → devuelve HTTP 402
3. Wallet del usuario paga 0.10 USDC en X Layer
4. Middleware verifica pago → deja pasar el request
5. Travel Agent busca en base de datos (Paris, agosto)
6. Travel Agent consulta clima si fecha es cercana
7. LLM razona y genera guia personalizada
8. Respuesta JSON con recomendaciones completas
```

## Estrategia para el hackathon (MVP)

Para el MVP del concurso (deadline 17 jul):
- Enfocarse en el **Travel Agent** (el que genera valor y cobra)
- Base de datos simple con 1-2 ciudades pre-cargadas manualmente
- Builder y Guardian como prompts disponibles (no necesariamente automatizados)
- Scheduler puede ser manual para la demo

Lo importante para el jurado:
- Que el flujo de pago funcione (x402 → respuesta)
- Que la respuesta sea de alta calidad
- Arquitectura de 3 agentes bien explicada (demuestra vision)
