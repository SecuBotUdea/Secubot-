# Secubot — Motor de Gamificación

Microservicio del ecosistema **SecuBot-UdeA** responsable de la lógica de gamificación. Recibe el resultado de rescans desde `jug-eared`, calcula los puntos del usuario según severidad, velocidad de resolución y score de referencias externas, persiste el historial y notifica el resultado a `jug-eared` para que lo reenvíe a Discord.

---

## Rol en la arquitectura

```
jug-eared ──► POST /events/rescan_result ──► Secubot ──► MongoDB (players, point_logs, remediations)
                                                    └──► POST GLORIA_URL/gamification/ (jug-eared)
```

Secubot no se comunica con GitHub, Discord ni `parser-dependabot`. Solo procesa resultados ya resueltos que le llegan de `jug-eared`.

---

## Endpoints

### `POST /events/rescan_result`

Procesa el resultado de un rescan. Si el `status` es `fixed` o `resolved`, calcula y otorga puntos al usuario. Cualquier otro valor se registra como intento inválido sin otorgar puntos.

**Requiere `user_id`** — si no viene en el payload, retorna `422`.

**Body (`RescanResultPayload`):**
```json
{
  "alert_id": "dependabot-pangoaguirre-learndependabot-12",
  "team_id": "team-001",
  "team_name": "Equipo Alpha",
  "user_id": "987654321",
  "status": "fixed",
  "severity": "high",
  "source_type": "dependabot",
  "title": "CVE-2024-XXXX en lodash",
  "component": "lodash",
  "location": "package.json",
  "external_references_score": 0.85,
  "opened_at": "2026-06-08T10:00:00+00:00",
  "normalized_payload": {}
}
```

**Respuesta — puntos otorgados:**
```json
{
  "status": "points_awarded",
  "points": 135,
  "alert_id": "dependabot-pangoaguirre-learndependabot-12",
  "user_id": "987654321",
  "breakdown": {
    "base": 75,
    "speed_multiplier": 1.5,
    "score_multiplier": 1.2,
    "penalty": 0
  }
}
```

**Respuesta — sin puntos (status inválido):**
```json
{
  "status": "no_points",
  "alert_id": "dependabot-pangoaguirre-learndependabot-12",
  "user_id": "987654321"
}
```

---

### `GET /teams/{team_id}/leaderboard`

Top 10 jugadores del equipo ordenados por puntos.

```json
[
  { "user_id": "987654321", "points": 270, "rank": 1 },
  { "user_id": "111222333", "points": 50,  "rank": 2 }
]
```

---

### `GET /teams/{team_id}/players/{user_id}`

Detalle del jugador: puntos totales, ranking actual e historial de puntos ganados.

```json
{
  "user_id": "987654321",
  "team_id": "team-001",
  "points": 270,
  "rank": 1,
  "point_logs": [
    { "alert_id": "dependabot-pangoaguirre-learndependabot-12", "points": 135, "timestamp": "2026-06-09T10:00:00+00:00" },
    { "alert_id": "dependabot-pangoaguirre-learndependabot-7",  "points": 135, "timestamp": "2026-06-08T14:00:00+00:00" }
  ]
}
```

---

### `GET /health`

```json
{
  "status": "healthy",
  "database_connected": true,
  "timestamp": "2026-06-09T10:00:00+00:00"
}
```

`status` es `healthy` solo si MongoDB está conectado. Si se usa backend en memoria, reporta `degraded`.

---

## Lógica de puntos

### Puntos base por severidad

| Severidad | Puntos base |
|---|---|
| `critical` | 100 |
| `high` | 75 |
| `medium` | 50 |
| `low` | 25 |
| `informational` / `unknown` / null | 10 |

### Multiplicador de velocidad (`speed_multiplier`)

Basado en el tiempo transcurrido desde `opened_at` hasta el momento del rescan:

| Tiempo transcurrido | Multiplicador |
|---|---|
| < 6 horas | 1.5× |
| 6 – 24 horas | 1.25× |
| 24 – 72 horas | 1.1× |
| > 72 horas | 1.0× |

Si `opened_at` no se provee, el multiplicador es `1.0`.

### Multiplicador de score externo (`score_multiplier`)

Basado en `external_references_score` (0.0 – 1.0, ej. score CVSS normalizado):

| Score | Multiplicador |
|---|---|
| ≥ 0.7 | 1.5× |
| 0.4 – 0.69 | 1.2× |
| < 0.4 o null | 1.0× |

### Penalización por intentos inválidos

Por cada intento inválido previo del mismo usuario sobre el mismo `alert_id`:

```
penalización = min(30, intentos_inválidos × 10)
```

### Fórmula final

```
puntos = max(1, round(base × speed_multiplier × score_multiplier) − penalización)
```

El mínimo siempre es 1 punto.

---

## Flujo interno por evento

```
POST /events/rescan_result
  │
  ├─ Validar payload (RescanResultPayload)
  ├─ Verificar user_id presente
  │
  ├─ [status inválido]
  │     ├─ RemediationRepository.add_remediation (status, points=0)
  │     └─ GloriaService.notify_rescan_result (points=0)
  │
  └─ [status fixed/resolved]
        ├─ RemediationRepository.count_invalid_attempts (para calcular penalización)
        ├─ Calcular puntos (base × speed × score − penalización)
        ├─ PlayerRepository.add_points
        ├─ PointLogRepository.add_log
        ├─ RemediationRepository.add_remediation (status, points)
        └─ GloriaService.notify_rescan_result → POST GLORIA_URL/gamification/
```

`GloriaService` falla silenciosamente: si la notificación a `jug-eared` falla, los puntos ya fueron persistidos y el error queda en logs sin revertir la operación.

---

## Base de datos

| Colección | Contenido |
|---|---|
| `players` | Puntos acumulados por `(user_id, team_id)`. Upsert atómico con `$inc`. |
| `point_logs` | Un registro por cada rescan válido: `user_id`, `team_id`, `alert_id`, `points`, `timestamp`. |
| `remediations` | Todos los intentos (válidos e inválidos): `alert_id`, `user_id`, `team_id`, `status`, `points_awarded`, `attempted_at`. Sirve de auditoría y para contar penalizaciones. |

---

## Variables de entorno

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `DATABASE_URL` | No | `memory://local` | URI MongoDB Atlas (`mongodb+srv://...`). Sin configurar, usa backend en memoria. |
| `GLORIA_URL` | No | `null` | URL base de `jug-eared`, ej. `http://jug-eared:8000`. Sin configurar, las notificaciones se omiten silenciosamente. |
| `HTTP_PORT` | No | `8000` | Puerto del servidor HTTP |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging |
| `ENVIRONMENT` | No | `development` | `development` / `production` |
| `ALLOWED_ORIGINS` | No | `""` | CSV de orígenes CORS permitidos |

---

## Instalación y ejecución local

```bash
git clone https://github.com/SecuBotUdea/Secubot-.git
cd Secubot-

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # completar con valores reales
python main.py
```

Sin `DATABASE_URL`, el servicio arranca con backend en memoria (útil para desarrollo y tests).

---

## Tests

```bash
pytest tests/ -v
```

No requiere MongoDB ni `jug-eared` — el backend en memoria se activa automáticamente. La suite cubre endpoints HTTP, lógica de puntos (multiplicadores, penalizaciones), registro de remediaciones y comportamiento de `GloriaService` ante fallos.

---

## Despliegue con Docker

```bash
docker build -t secubot .
docker run -p 8000:8000 --env-file .env secubot
```

---

## Despliegue en Kubernetes

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml      # copiar de secret.example.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Secubot es un servicio interno — solo recibe tráfico de `jug-eared` dentro del clúster (ClusterIP, sin Ingress necesario).

---

## Estructura del proyecto

```
app/
├── config/
│   └── settings.py                # Settings (pydantic-settings)
├── database/
│   └── connection.py              # DatabaseManager, InMemory/Mongo repos, points_for_severity
├── models/
│   ├── alert.py                   # AlertRecord
│   ├── player.py                  # PlayerRecord
│   ├── point_log.py               # PointLogRecord
│   └── remediation.py             # RemediationRecord
├── schemas/
│   └── common.py                  # RescanResultPayload, PlayerDetail, LeaderboardEntry, HealthResponse
├── services/
│   ├── gamification_service.py    # Lógica de puntos, multiplicadores, penalizaciones
│   └── gloria_service.py          # Cliente HTTP para notificar a jug-eared
└── http.py                        # FastAPI app factory
main.py
```

---

## Notas

- El leaderboard está limitado a los **top 10** jugadores por equipo (límite en la consulta MongoDB).
- Los puntos se acumulan con `$inc` atómico en MongoDB — no hay riesgo de condición de carrera en entornos con múltiples instancias.
- Si `DATABASE_URL` falla al conectar, el servicio arranca igualmente con backend en memoria y loguea una advertencia. Los datos no persisten entre reinicios en ese modo.
