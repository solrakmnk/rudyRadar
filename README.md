# Radar Rudy

Radar Rudy es el tablero privado de RUD@S. Usa FastAPI, PostgreSQL y Strava OAuth para verificar miembros y, cuando `STRAVA_SYNC_ENABLED=true`, sincronizar las actividades autorizadas.

## Requisitos

Git, Docker y Docker Compose.

```sh
git clone git@github.com:solrakmnk/rudyRadar.git
cd rudyRadar
cp .env.example .env
docker compose up --build
docker compose exec app alembic upgrade head
docker compose exec app pytest
```

Abre <http://localhost:8000>. El admin está en `/admin`; envía `Authorization: Bearer <ADMIN_SECRET>` al abrirlo mediante una herramienta HTTP o extensión de navegador.

## Configuración Strava

Completa `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY`, `SESSION_SECRET` y `ADMIN_SECRET`. En Strava API Settings configura el Authorization Callback Domain para el dominio del callback; localmente usa `localhost`, y configura `STRAVA_REDIRECT_URI=http://localhost:8000/auth/strava/callback`.

El flujo solicita `read,profile:read_all,activity:read`, consulta `/athlete/clubs` en el servidor y usa `GET /athlete` como respaldo oficial para comprobar sus clubes. Permite entrar solamente al club `1187973`. No se guardan GPS, polylines ni datos biométricos.

Por defecto `STRAVA_SYNC_ENABLED=false`: OAuth y validación de club están implementados, pero no se descargan actividades reales. Actívalo solamente tras confirmar que el uso previsto cumple las condiciones vigentes de Strava. Los tests no contactan Strava.

## Railway

Crea un servicio PostgreSQL y un servicio desde este repositorio usando el Dockerfile. Copia las variables de `.env.example`, reemplaza `DATABASE_URL` por la que entrega Railway y ajusta `APP_BASE_URL` y `STRAVA_REDIRECT_URI` a HTTPS. Ejecuta `alembic upgrade head` una vez desde el shell de Railway antes de habilitar tráfico.

Configura un Cron Job de Railway cada 6 horas con `python -m app.cli`; sincroniza los atletas activos y evita depender exclusivamente de webhooks. Para sincronización cercana a tiempo real registra `https://<dominio>/webhooks/strava` como callback de Strava y define `WEBHOOK_VERIFY_TOKEN`. Los webhooks `create`, `update` y `delete` son idempotentes y la app consulta Strava para obtener la actividad completa antes de persistirla.

## Privacidad y desconexión

La aplicación debe borrar actividades y tokens cuando un atleta revoca acceso o solicita eliminación. El endpoint de desautorización y el procesamiento completo de eventos webhook están preparados como siguiente fase; configura `WEBHOOK_VERIFY_TOKEN` para habilitar la verificación de suscripción.
