# Secubot — Microservicio de Gamificacion de Seguridad

Microservicio REST que actua como motor de gamificacion para un bot de Discord orientado a ciberseguridad. Recompensa a los usuarios que detectan y validan alertas de seguridad en su servidor.

## Como funciona

El flujo principal tiene dos pasos:

1. **Llega una alerta** — un sistema externo (ej. Wazuh/SIEM) envia la alerta via `POST /events/alert` con severidad y metadatos.
2. **Un usuario la valida** — cuando el parser externo confirma que la correccion es valida, se notifica via `POST /events/rescan_result`. Si el estado es `"valid"`, el usuario recibe puntos segun la gravedad. Secubot notifica el resultado a **Gloria** (servicio de enrutamiento), que a su vez avisa al bot de Discord.

| Severidad  | Puntos |
|------------|--------|
| `critical` | 100    |
| `high`     | 75     |
| `medium`   | 50     |
| `low`      | 25     |

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| `POST` | `/events/alert` | Registra una nueva alerta de seguridad |
| `POST` | `/events/rescan_result` | Resultado del re-escaneo; otorga puntos si es valido |
| `GET`  | `/teams/{guild_id}/leaderboard` | Tabla de posiciones del servidor de Discord |
| `GET`  | `/teams/{guild_id}/players/{user_id}` | Detalle del jugador (puntos, ranking, historial) |
| `GET`  | `/health` | Estado del servicio y de la base de datos |

### Ejemplos de payload

**POST /events/alert**
```json
{
  "alert_id": "alert_123",
  "guild_id": "111",
  "channel_id": "222",
  "severity": "high",
  "source": "wazuh",
  "description": "Suspicious login attempt detected"
}
```

**POST /events/rescan_result**
```json
{
  "alert_id": "alert_123",
  "user_id": "user_456",
  "status": "valid"
}
```

## Stack tecnico

- **Python 3.11+** con `asyncio`
- **FastAPI** + **Uvicorn** como servidor HTTP
- **MongoDB** via `motor` (driver async) como backend principal
- **Fallback en memoria** cuando MongoDB no esta disponible o se usa `memory://` como URL
- **Pydantic v2** para validacion de esquemas y settings
- **Docker** listo para produccion

## Estructura del proyecto

```
secubot/
├── main.py                               # Punto de entrada, arranque del servidor
├── app/
│   ├── http.py                           # Definicion de rutas FastAPI
│   ├── config/settings.py                # Configuracion via variables de entorno
│   ├── database/connection.py            # Repositorios Mongo + fallback en memoria
│   ├── models/                           # Modelos de datos (Alert, Player, PointLog)
│   ├── schemas/common.py                 # Schemas de entrada/salida de la API
│   ├── services/gamification_service.py  # Logica de negocio principal
│   └── services/gloria_service.py        # Cliente HTTP para notificar a Gloria
├── tests/
│   ├── test_http_endpoints.py            # Tests de endpoints y gamificacion
│   └── test_gloria_integration.py        # Tests de integracion con Gloria
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Variables de entorno

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `DATABASE_URL` | `memory://local` | URL de MongoDB (ej. `mongodb+srv://user:pass@cluster/secubot`) |
| `HTTP_PORT` | `8000` | Puerto del servidor |
| `LOG_LEVEL` | `INFO` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ENVIRONMENT` | `development` | Entorno de ejecucion |
| `ALLOWED_ORIGINS` | `` | Origenes CORS permitidos (separados por coma) |
| `GLORIA_URL` | _(ninguno)_ | URL base del servicio Gloria (ej. `http://gloria:8001`). Si no se configura, las notificaciones se omiten silenciosamente. |

## Ejecucion

### Con Python

```bash
cp .env.example .env
# Editar .env con los valores correctos

pip install -r requirements.txt
python main.py
```

### Con Docker

```bash
docker build -t secubot .
docker run -p 8000:8000 --env-file .env secubot
```

## Tests

```bash
pytest tests/
```

El backend en memoria (`memory://`) se usa automaticamente en los tests, sin necesidad de una instancia de MongoDB ni de una instancia de Gloria.

La suite cubre:

- Endpoints HTTP (respuestas, codigos de error, schemas)
- Logica de gamificacion (puntos por severidad, proteccion contra doble otorgamiento)
- Integracion con Gloria: payload correcto, fire-and-forget ante fallos, no-op sin `GLORIA_URL`
