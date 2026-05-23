# Secubot — Microservicio de Gamificacion de Seguridad

Microservicio REST que actua como motor de gamificacion del ecosistema SecuBot-UdeA. Recompensa a los usuarios que detectan y corrigen alertas de seguridad en su repositorio.

## Como funciona

El flujo principal tiene dos pasos:

1. **Llega una alerta** — Gloria (servicio de enrutamiento) envia la alerta normalizada via `POST /events/alert`. Secubot la almacena y registra al equipo automaticamente si es la primera alerta.
2. **Un usuario la corrige** — cuando el Parser externo confirma que la correccion es valida, notifica via `POST /events/rescan_result`. Si el estado es `"valid"`, el usuario recibe puntos segun la severidad. Secubot notifica el resultado a Gloria, que avisa al bot de Discord del equipo.

| Severidad | Puntos |
|-----------|--------|
| `critical` | 100 |
| `high` | 75 |
| `medium` | 50 |
| `low` | 25 |
| `informational` / `unknown` / null | 10 |

Cada alerta solo puede resolverse una vez. Un segundo intento sobre una alerta ya resuelta devuelve `409`. Los intentos invalidos no restan puntos y permiten reintentar.

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| `POST` | `/events/alert` | Registra una nueva alerta normalizada |
| `POST` | `/events/rescan_result` | Resultado del rescan; otorga puntos si es valido |
| `GET` | `/teams/{team_id}/leaderboard` | Top 10 jugadores del equipo |
| `GET` | `/teams/{team_id}/players/{user_id}` | Detalle del jugador: puntos, ranking, historial |
| `GET` | `/health` | Estado del servicio y de la base de datos |

### Payloads

**POST /events/alert**
```json
{
  "alert_id": "dependabot-pangoaguirre-learndependabot-12",
  "team_id": "123456789",
  "channel_id": "987654321",
  "severity": "high",
  "source_type": "dependabot",
  "title": "Lodash vulnerable to prototype pollution"
}
```

**POST /events/rescan_result**
```json
{
  "alert_id": "dependabot-pangoaguirre-learndependabot-12",
  "user_id": "user_456",
  "status": "valid"
}
```

**GET /teams/{team_id}/leaderboard**
```json
[
  { "user_id": "user_456", "points": 175, "rank": 1 },
  { "user_id": "user_789", "points": 50,  "rank": 2 }
]
```

**GET /teams/{team_id}/players/{user_id}**
```json
{
  "user_id": "user_456",
  "team_id": "123456789",
  "points": 175,
  "rank": 1,
  "point_logs": [
    { "alert_id": "...", "points": 75, "timestamp": "2026-05-21T10:00:00+00:00" }
  ]
}
```

## Base de datos

| Coleccion | Proposito |
|-----------|-----------|
| `alerts` | Estado de cada alerta (`open` / `resolved`) |
| `players` | Puntos totales por jugador y equipo |
| `point_logs` | Historial de puntos ganados (solo intentos validos) |
| `remediations` | Todos los intentos de rescan, validos e invalidos (trazabilidad) |

## Stack tecnico

- **Python 3.11+** con `asyncio`
- **FastAPI** + **Uvicorn**
- **MongoDB** via `motor` (driver async)
- **Fallback en memoria** cuando MongoDB no esta disponible o se usa `memory://` como URL
- **Pydantic v2** para validacion de esquemas y settings
- **httpx** para notificaciones a Gloria

## Estructura del proyecto

```
secubot/
├── main.py                               # Punto de entrada
├── app/
│   ├── http.py                           # Rutas FastAPI y manejo de errores
│   ├── config/settings.py                # Variables de entorno (pydantic-settings)
│   ├── database/connection.py            # Repositorios Mongo + fallback en memoria
│   ├── models/                           # Modelos internos (Alert, Player, PointLog, Remediation)
│   ├── schemas/common.py                 # Contratos HTTP (Pydantic)
│   ├── services/gamification_service.py  # Logica de negocio principal
│   └── services/gloria_service.py        # Cliente HTTP para notificar a Gloria
├── tests/
│   ├── test_http_endpoints.py            # Tests de endpoints, gamificacion y remediaciones
│   └── test_gloria_integration.py        # Tests de integracion con Gloria
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── secret.example.yaml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Variables de entorno

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `DATABASE_URL` | `memory://local` | URL de MongoDB (`mongodb+srv://...`) o `memory://` para modo local |
| `HTTP_PORT` | `8000` | Puerto del servidor |
| `LOG_LEVEL` | `INFO` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ENVIRONMENT` | `development` | Entorno de ejecucion |
| `ALLOWED_ORIGINS` | _(ninguno)_ | Origenes CORS permitidos, separados por coma |
| `GLORIA_URL` | _(ninguno)_ | URL base de Gloria (ej. `http://gloria:8001`). Sin configurar, las notificaciones se omiten silenciosamente. |

## Ejecucion

### Con Python

```bash
cp .env.example .env
# Editar .env con los valores reales

pip install -r requirements.txt
python main.py
```

### Con Docker

```bash
docker build -t secubot .
docker run -p 8000:8000 --env-file .env secubot
```

### Con Kubernetes

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml      # copiar de secret.example.yaml con valores reales
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Secubot es un servicio interno — solo recibe trafico de Gloria dentro del cluster (ClusterIP, sin Ingress).

## Tests

```bash
pytest tests/ -v
```

El backend en memoria se usa automaticamente, sin necesidad de MongoDB ni Gloria.

La suite cubre:

- Endpoints HTTP (respuestas, codigos de error, schemas)
- Logica de gamificacion (puntos por severidad, proteccion contra doble otorgamiento, reintentos invalidos)
- Registro de remediaciones (todos los intentos quedan auditados)
- Integracion con Gloria: payload correcto, fire-and-forget ante fallos, no-op sin `GLORIA_URL`
