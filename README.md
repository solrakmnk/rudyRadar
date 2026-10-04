# Radar Rudo

Radar Rudo es el tablero privado de RUD@S. Rudy es el asistente que encuentra las historias en los entrenamientos. Usa FastAPI, PostgreSQL y Strava OAuth para verificar miembros y, cuando `STRAVA_SYNC_ENABLED=true`, sincronizar las actividades autorizadas.

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

El alta solicita por defecto `activity:read` para importar actividades visibles para Todos o Seguidores. Una vez dentro, cada atleta puede habilitar `activity:read_all` para incluir las configuradas como Solo tú, o retirarlo nuevamente desde Configuración. El alcance concedido se valida y guarda, junto con la visibilidad de cada actividad; al retirar el acceso privado se eliminan de Radar las actividades que ya no son accesibles y se recalculan los totales. Además solicita `read,profile:read_all`, consulta `/athlete/clubs` en el servidor y usa `GET /athlete` como respaldo oficial para comprobar sus clubes. Permite entrar solamente al club `1187973`. No se guardan GPS, polylines, rutas ni secuencias biométricas.

Por defecto `STRAVA_SYNC_ENABLED=false`: OAuth y validación de club están implementados, pero no se descargan actividades reales. Actívalo solamente tras confirmar que el uso previsto cumple las condiciones vigentes de Strava. Los tests no contactan Strava.

## Railway

Crea un servicio PostgreSQL y un servicio desde este repositorio usando el Dockerfile. Copia las variables de `.env.example`, reemplaza `DATABASE_URL` por la que entrega Railway y ajusta `APP_BASE_URL` y `STRAVA_REDIRECT_URI` a HTTPS. Ejecuta `alembic upgrade head` una vez desde el shell de Railway antes de habilitar tráfico.

El contenedor ejecuta `alembic upgrade head` antes de iniciar la aplicación, por lo que cada despliegue aplica las migraciones pendientes. Los webhooks de Strava son la fuente principal de actualizaciones; `https://<dominio>/webhooks/strava` debe estar registrado como callback y `WEBHOOK_VERIFY_TOKEN` debe estar definido. Los eventos `create`, `update` y `delete` son idempotentes y la app consulta Strava para obtener la actividad completa antes de persistirla. Un Cron Job de Railway con `python -m app.cli` corre cada 2 horas únicamente como reconciliación de respaldo.

## Entrega continua

El workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) compila el código, prueba contra PostgreSQL y aplica migraciones para cada pull request y push a `master`. Railway está conectado directamente a `solrakmnk/rudyRadar`, por lo que se encarga de desplegar los cambios de producción sin guardar tokens de Railway en GitHub Actions.

## Pendientes de producción

- Conectar un dominio propio corto para Rudo Radar. El dominio generado por Railway incluye el nombre del entorno (`rudo-radar-production.up.railway.app`); un dominio propio, por ejemplo `rudo-radar.com`, permite una URL limpia.
- Actualizar `APP_BASE_URL`, `STRAVA_REDIRECT_URI` y el callback de Strava cuando ese dominio esté verificado.

## Privacidad y desconexión

La aplicación debe borrar actividades y tokens cuando un atleta revoca acceso o solicita eliminación. El endpoint de desautorización y el procesamiento completo de eventos webhook están preparados como siguiente fase; configura `WEBHOOK_VERIFY_TOKEN` para habilitar la verificación de suscripción.
