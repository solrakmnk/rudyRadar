# Auditoría de la integración con Strava — Radar Rudo (App ID 25116)

Fecha: 10 de noviembre de 2026. Alcance: sincronización de actividades, webhooks, tokens, desconexiones y consumo de la API. La auditoría revisó el código y, en modo de solo lectura, la configuración y los logs de Railway. No se modificó producción.

---

## 1. Arquitectura anterior (antes de este cambio)

| Componente | Dónde | Qué consulta a Strava |
|---|---|---|
| OAuth callback | `app/main.py::callback` | `POST /oauth/token`, `GET /athlete/clubs` (paginado, con respaldo `GET /athlete`) y `GET /athlete/activities` |
| Importación | `app/sync.py::sync_activities` | `GET /athlete/activities?after=…&per_page=200`, paginado |
| Webhook | `app/main.py::receive_webhook` / `process_webhook` | `GET /activities/{id}` por cada `create` y `update` |
| Cron `rudo-sync` (`0 */2 * * *`, `python -m app.cli`) | `app/cli.py` → `app/sync.py::sync_all_active_athletes` | Por atleta y por ejecución: `GET /athlete/clubs` y `GET /athlete/activities` de los últimos 21 días |
| Cron `rudo-sync-daytime` / `rudo-sync-evening` (`0 0 1 1 *`) | Comando `true` | Nada (están inertes) |
| Revalidación admin | `app/main.py::revalidate_athlete` | `GET /athlete/clubs` |
| Borrado de cuenta | `app/main.py::delete_my_data` | `POST /oauth/deauthorize` |
| Registro de suscripción | `app/webhooks.py::ensure_strava_webhook` | `GET`/`POST /push_subscriptions` al arrancar |

Datos: `athletes` (tokens cifrados con Fernet en `access_token_encrypted` y `refresh_token_encrypted`), `activities` (clave única `strava_activity_id`). No existía un registro de los eventos del webhook.

**Consumo medido en los logs de Railway (8 al 10 de noviembre):** `rudo-sync` corrió 12 veces al día con `{"athletes": 10, "activities": ~245, "failed": 0}`. Cada ejecución hacía unas **20 solicitudes** (10 de clubes y 10 de actividades), es decir, **~240 solicitudes al día**, y volvía a descargar unas **2,900 actividades al día**. Casi todas no tenían cambios porque los webhooks ya las habían entregado. En el mismo periodo el webhook recibió entre 15 y 25 eventos diarios.

## 2. Problemas encontrados

| # | Problema | Referencia | Impacto |
|---|---|---|---|
| P1 | Polling periódico: cada 2 h se descargaba de nuevo una ventana de 21 días para cada atleta | `app/sync.py::sync_all_active_athletes`, `app/cli.py` | ~240 solicitudes al día redundantes con los webhooks; es justo lo que Strava pidió eliminar |
| P2 | Cada inicio de sesión (`mode=login` pide `activity:read_all`, así que `requested_private=True`) volvía a importar 365 días | `app/main.py::callback` (`lookback_days`) | Varias páginas de `/athlete/activities` en cada login |
| P3 | Los eventos se procesaban en `BackgroundTasks` en memoria, sin persistencia | `receive_webhook` | Un redeploy o una caída perdía el evento después de responder 200 |
| P4 | Sin reintentos: cualquier error terminaba en `logger.exception` y el evento se perdía | `process_webhook` | Un 5xx o 429 de Strava dejaba la actividad sin actualizar |
| P5 | Sin idempotencia a nivel de evento ni control de orden | `process_webhook` | Las reentregas y los eventos fuera de orden volvían a llamar a la API |
| P6 | Cada `update` llamaba a `GET /activities/{id}`, aunque solo cambiara el título o el tipo | `process_webhook` | Solicitudes innecesarias |
| P7 | La desautorización se ignoraba si el atleta estaba inactivo (el filtro `is_active=True` se aplicaba antes) | `process_webhook` | Quedaban datos de atletas que revocaron el acceso |
| P8 | Un 429 se trataba igual que cualquier error, sin backoff ni pausa | `services.py::_request` | Riesgo de seguir llamando estando limitado |
| P9 | `refresh()` no capturaba timeouts y trataba cualquier 4xx o 5xx igual; no había manejo de 401 | `services.py` | Reintentos sin fin con credenciales inválidas, o desconexiones falsas por fallas transitorias |
| P10 | `deauthorize` usaba `/api/v3/oauth/deauthorize` en lugar de `https://www.strava.com/oauth/deauthorize` | `services.py::deauthorize` | Al borrar la cuenta, el acceso no se revocaba en Strava (el error solo se registraba como warning) |
| P11 | Sin configuración de logging: los `logger.info` (por ejemplo "Processed Strava webhook") nunca se emitían | `app/main.py` | Un HTTP 200 no permitía saber si el evento se había procesado |
| P12 | No se validaba el `subscription_id` | `receive_webhook` | Cualquiera podía provocar llamadas a la API con eventos falsos |
| P13 | `delete_my_data` revocaba el acceso con un access token posiblemente expirado | `delete_my_data` | La revocación fallaba |

## 3. Requisitos que ya se cumplían

- La verificación `GET /webhooks/strava` (`hub.mode`, `hub.verify_token`, `hub.challenge`) era correcta.
- Las actividades se deduplicaban con la clave única `strava_activity_id` y `upsert_activity`.
- La importación paginaba con `per_page=200`.
- Los tokens se guardaban cifrados y se renovaban 5 minutos antes de expirar.
- El borrado de una actividad se aplicaba localmente; la desautorización borraba al atleta (con el defecto P7).
- Los permisos mínimos y la conciliación al retirar `activity:read_all` ya estaban implementados.
- Las suscripciones se registraban al arrancar.

## 4. Requisitos que estaban pendientes (y ahora están implementados)

Eliminar el polling, persistir eventos, reintentos controlados, eventos duplicados y fuera de orden, evitar fetch innecesarios, manejo de 401, 403, 404 y 429, exclusión de atletas desconectados, registrar el resultado de la importación inicial, métricas de consumo y diagnóstico de eventos no procesados.

## 5. Riesgos de modificar el cron

- `rudo-sync` despliega desde la rama por defecto del repo con `python -m app.cli`. **Borrar `app/cli.py` lo habría roto.** El comando se conserva con el mismo nombre y ahora solo hace mantenimiento.
- Si `rudo-sync` corre con el código nuevo antes de que `rudo-radar` aplique la migración 0013, cada paso falla de forma aislada: se registra el error y el proceso termina con código 0.
- La revalidación de membresía pasa de cada 2 h a una vez por semana por atleta. También se revalida en cada login y desde `/admin`.
- Antes, un webhook perdido se corregía solo en la siguiente ejecución del cron. Ahora lo cubren la cola persistente, los reintentos y, como último recurso, `recover` manual.

## 6. Plan de corrección aplicado (por prioridad)

1. Persistir eventos antes del 200 y procesarlos fuera del request, con idempotencia (P3, P5, P11).
2. Reintentos con backoff y clasificación de errores (P4, P8, P9).
3. Eliminar el polling sin romper el cron (P1).
4. Quitar las importaciones redundantes en el login (P2).
5. Tokens y desconexiones (P7, P9, P10, P13).
6. Evitar fetch innecesarios y validar la suscripción (P6, P12).
7. Métricas y diagnóstico.

---

## 7. Cambios realizados

| Archivo | Cambio |
|---|---|
| `app/strava_events.py` (nuevo) | Cola durable de eventos: `record_event` (deduplica con una restricción única sobre owner, objeto, aspecto y `event_time`), `claim_event` (UPDATE atómico a `processing` con lease de 15 min), `_apply` (reglas de negocio), `process_event` (clasifica errores), `process_due_events`, `release_expired_leases`, `purge_old_events`, `event_summary` y `requeue_failed`. |
| `app/services.py` | Errores tipados: `StravaTransientError`, `StravaRateLimitError` (con `retry_after`), `StravaAuthError`, `StravaForbiddenError` y `StravaNotFoundError`. `StravaApiMetrics` cuenta las llamadas por endpoint y por status y guarda los headers `X-RateLimit-*`. Después de un 429 bloquea las llamadas hasta que se reinicia la ventana (de 15 min o diaria). `call_with_token` hace un refresh forzado ante un 401 y reintenta una sola vez. `mark_reauthorization_required` cubre un refresh rechazado. Se corrigió la URL de `deauthorize`. El token endpoint distingue 4xx (credencial inválida) de 5xx o timeout (transitorio). La paginación tiene un tope de 25 páginas. |
| `app/sync.py` | `sync_activities` usa `call_with_token`. `import_history` registra `initial_import_status`, `initial_import_count` e `initial_import_error`. `recover_activities` es una recuperación manual limitada a 30 días. Se eliminó `sync_all_active_athletes`. |
| `app/main.py` | El webhook guarda el evento, responde 200 y procesa en segundo plano; ignora suscripciones ajenas y payloads mal formados. El callback solo consulta actividades en la primera conexión, si cambia el permiso privado o al reconectarse tras credenciales inválidas (solo los días faltantes). Se agregó `GET /admin/strava` con el diagnóstico, se configuró el logging y la revocación usa un token válido. |
| `app/webhooks.py` | Guarda el `subscription_id` activo. `retry_webhook_events_periodically` reintenta cada 60 s los eventos vencidos; solo consulta la base de datos si no hay pendientes. |
| `app/cli.py` | Ahora es un comando de mantenimiento: reintentos, revalidación semanal de membresía y depuración de eventos. Subcomandos `status`, `recover` y `requeue-failed`. Ningún paso consulta la lista de actividades. |
| `app/models.py`, `alembic/versions/0013_webhook_events.py` | Columnas nuevas en `athletes`: `auth_status`, `auth_error`, `auth_error_at`, `initial_import_status`, `initial_import_count` e `initial_import_error`. Tabla nueva `strava_webhook_events`. |
| `app/config.py`, `.env.example` | Variables opcionales `WEBHOOK_RETRY_INTERVAL_SECONDS` (60) y `MEMBERSHIP_REVALIDATION_DAYS` (7), y `LOG_LEVEL`. |
| `tests/` | `test_strava_events.py`, `test_initial_import.py`, un `test_webhooks.py` reescrito y un `conftest.py` que admite `TEST_DATABASE_URL`. |

### Reglas del procesamiento de eventos

| Evento | Acción | ¿Llama a Strava? |
|---|---|---|
| Entrega repetida (mismo owner, objeto, aspecto, `event_time` y hash de `updates`) | Se descarta; responde `{"status":"duplicate"}`. Dos cambios distintos en el mismo segundo se conservan los dos | No |
| Sin `subscription_id`, o distinto del activo | Se ignora | No |
| `subscription_id` activo todavía desconocido (por ejemplo, justo después del arranque) | Se guarda; el procesador consulta `GET /push_subscriptions` (como máximo una vez cada 5 min) y reintenta cada 5 min sin consumir intentos. Nada se aplica antes de verificarlo | 1 llamada de app |
| `athlete` `update` con `authorized=false` | Antes de borrar se confirma con Strava: si `GET /athlete` y el refresh son rechazados, se borra al atleta, sus actividades y su historial de eventos, esté activo o no. Si las credenciales siguen funcionando, el evento se ignora (`deauthorization_not_confirmed`) | 1–2 llamadas |
| `activity` `delete`, actividad no guardada localmente | `already_absent`: no hay nada que borrar | No |
| `activity` `delete`, actividad guardada | Se confirma con `GET /activities/{id}` antes de borrar (ver la sección de seguridad) | 1 llamada |
| Atleta desconocido, fuera del club o `reauth_required` | Se ignora | No |
| Evento anterior a una eliminación, o a un evento posterior que ya leyó el estado completo | `stale` o `already_deleted` | No |
| Hay un evento posterior pendiente que leerá el estado completo (alta, eliminación o cambio que no sea solo título o tipo) | `superseded`. Un cambio de solo título o tipo nunca reemplaza a otro evento | No |
| `update` con solo `title` y/o `type`, sin eventos posteriores | Se aplica desde el payload | No |
| Cualquier evento que tiene eventos posteriores para la misma actividad | Se lee el estado actual con `GET /activities/{id}`, para no sobrescribir valores nuevos. El orden es (`event_time`, id), porque `event_time` tiene resolución de un segundo | 1 llamada |
| `update` con `private` | Nunca se aplica desde el payload: se consulta la actividad, y solo la respuesta de Strava puede borrarla | 1 llamada |
| `create` u otro `update` | `GET /activities/{id}` y upsert | 1 llamada |
| Respuesta 404 | Borra la actividad local: ya no existe o ya no es visible con el permiso del atleta | — |
| Respuesta 403 sobre la actividad | Borra la actividad local (`not_accessible`): el permiso del atleta no permite verla | — |
| Respuesta 403 por un scope faltante en el token | No borra nada. El evento queda `failed`/`permission_denied` y el atleta `reauth_required` | — |
| Respuesta 401 | Refresh forzado y un solo reintento; si vuelve a fallar, `reauth_required` | ≤ 2 |
| Refresh rechazado (400 o 401) | `reauth_required` y el atleta se oculta; el evento queda `failed` sin reintentos | — |
| 5xx, timeout o error interno | Reintento con backoff de 1 min, 5 min, 15 min, 1 h y 6 h; después `failed` | — |
| 429 | Reintento después de que se reinicie la ventana; se detiene el resto de la cola | — |

### Correcciones de la revisión del PR #1

1. **Validación de suscripción:** el webhook ya no confía en eventos mientras `active_subscription_id` es `None`. Los guarda, los verifica contra Strava antes de aplicarlos y rechaza los que no traen `subscription_id`. Como los eventos de Strava no están firmados, la eliminación de un atleta además requiere que Strava confirme que sus credenciales fueron revocadas.
2. **`history_done`:** depende solo de `history_synced_at` y de `initial_import_status == "completed"`, así que un atleta sin actividades ya no se reimporta en cada login.
3. **Deduplicación:** la clave incluye `payload_hash` (SHA-256 del `updates` canónico). Las reglas de orden ya no descartan un evento que necesita fetch por culpa de un cambio posterior de solo título o tipo.
4. **`clubs()`:** el fallback a `GET /athlete` solo ocurre ante un 403. Los 429, 5xx, timeouts y 401 se propagan. Además, un fallo transitorio de la verificación del club ya no desactiva a un miembro ya verificado (en el login ni en `/admin`).

### Seguridad de los webhooks (defensa en profundidad)

**Qué ofrece Strava.** Los eventos de la Webhook Events API **no están firmados**: no hay HMAC, ni secreto compartido, ni un header de autenticación en cada `POST`. El `verify_token` solo se usa una vez, en el `GET` de validación (`hub.mode`, `hub.verify_token`, `hub.challenge`) al crear la suscripción. Cada evento trae `object_type`, `object_id`, `aspect_type`, `owner_id`, `subscription_id`, `event_time` y `updates` (`title`, `type` y `private` para actividades; `authorized` para atletas). Strava no publica rangos de IP para los envíos. El `subscription_id` es un entero pequeño y predecible, así que no autentica al emisor.

**Riesgo real.** Quien conozca la URL del callback y el `subscription_id` puede enviar eventos. Antes de esta corrección, un `activity/delete` falso borraba la actividad sin consultar a Strava, y un `update` falso con `private=true` también la borraba (si el atleta no había concedido `activity:read_all`). Los `create` y `update` falsos no eran destructivos porque siempre se consultaba la actividad a Strava.

**Medidas implementadas:**

1. **Validación estricta del payload**, antes de guardar el evento:
   - Ids enteros positivos (no strings, floats ni booleanos) y `subscription_id` obligatorio.
   - Combinaciones válidas de `object_type` y `aspect_type`; los eventos de atleta solo pueden ser `update` con `authorized` y `object_id == owner_id`.
   - Solo las claves documentadas en `updates`, con `private` y `authorized` en `"true"`/`"false"`, y títulos de 255 caracteres como máximo.
   - `event_time` entre 7 días atrás y 10 minutos en el futuro.
   - Cuerpo de 4 KB como máximo (si no, 413).
2. **`subscription_id` verificado** contra el de la app, como ya hacía el PR.
3. **Las acciones destructivas solo ocurren cuando Strava las confirma:**
   - **`delete`:** si la actividad no está guardada, no se llama a la API. Si está, se consulta `GET /activities/{id}`:
     - 404: se borra (eliminada, u oculta para este permiso).
     - 200: la actividad se conserva y se refresca (`delete_not_confirmed`), salvo que ahora sea privada y el atleta no tenga `activity:read_all`.
     - 403 sobre la actividad: se borra (`not_accessible`).
     - 403 por scope faltante: no se borra nada y el atleta debe reconectarse.
     - 401: un refresh y un reintento. Si se rechaza, no se borra nada.
     - 429, 5xx o timeout: se reintenta con backoff y **nunca se borra**. Si se agotan los intentos, el evento queda `failed` y la actividad se conserva.
   - **`update` con `private`:** siempre se consulta la actividad; un evento falso con `private=true` sobre una actividad pública solo la refresca.
   - **Atleta sin credenciales válidas:** el borrado no se puede verificar. La actividad se conserva (el atleta ya está oculto) y el evento se vuelve a encolar automáticamente cuando el atleta se reconecta por OAuth.
   - **Eventos posteriores:** solo una eliminación confirmada puede suprimirlos. Un `delete` sin verificar no impide procesar un `create` posterior.
   - **Desautorización:** se conserva la confirmación del PR (credenciales rechazadas por Strava antes de borrar al atleta).
4. **Protección de la cuota:** si los headers `X-RateLimit-*` de la ventana actual muestran un uso de al menos el 90 % (de 15 min o diario), las llamadas se aplazan hasta que la ventana se reinicia, sin enviar la solicitud. Así una ráfaga de eventos, legítimos o falsos, no agota la cuota que necesitan los atletas reales.

**Costo en solicitudes:** una llamada por cada `delete` de una actividad guardada y por cada cambio de privacidad. Con 10 atletas eso son de 0 a 3 solicitudes al día; los deletes de actividades no guardadas cuestan 0. No hay polling ni consultas masivas.

**Riesgos residuales (no se pueden eliminar técnicamente sin cambios de Strava):**

- **Eventos falsos que gastan cuota:** un atacante que conozca el `subscription_id` y los `owner_id` puede provocar llamadas a la API con `create` falsos (una por evento). Lo limita la deduplicación, el freno al 90 % y la pausa ante un 429, pero no se puede impedir mientras Strava no firme sus eventos.
- **Cambios de título o tipo falsos:** se aplican desde el payload para ahorrar llamadas. No son destructivos y el siguiente evento real o fetch los corrige, pero pueden alterar temporalmente el título o la disciplina de una actividad.
- **Eventos legítimos aplazados:** un atacante puede retrasar el procesamiento de eventos legítimos llevando la cuota al 90 %; los eventos se aplazan, no se pierden.
- **Mejora posible no implementada:** registrar la suscripción con un callback que contenga un secreto difícil de adivinar (por ejemplo `/webhooks/strava/<token>`). Haría falta recrear la suscripción en Strava, que es un cambio de producción, por lo que no se aplicó.

## 8. Pruebas ejecutadas

- `pytest -q` sobre SQLite: **147 pasadas** (19 en `tests/test_review_regressions.py` y 42 en `tests/test_webhook_security.py`).
- `TEST_DATABASE_URL=postgresql+psycopg://… pytest -q` sobre PostgreSQL 16: **147 pasadas**.
- Migración en PostgreSQL 16: `upgrade 0012 → 0013` con datos previos (el atleta con historial queda `completed` y el que no tiene queda `pending`), `downgrade` y `upgrade` sin pérdida de datos.
- Prueba de humo con uvicorn y PostgreSQL: el webhook responde 200 en ~80 ms; la segunda entrega devuelve `duplicate`; `delete` se aplica sin llamar a la API; un owner desconocido queda `ignored`; `/admin/strava` y `python -m app.cli` y `status` funcionan. Una falla de descifrado se registra sin tumbar el comando.

Cobertura de los escenarios pedidos: primera conexión e importación paginada, login sin descargas, cambio de permisos, reconexión con recuperación del hueco, 429 en la importación; alta, actualización (desde el payload y con fetch), eliminación, duplicados, eventos fuera de orden y reemplazados, eliminación seguida de un alta tardía; token expirado, 401 con refresh, refresh revocado, 401 persistente; atleta desconectado, desautorización (también de atletas inactivos); 5xx con backoff, reintentos acotados, 429 con bloqueo, error interno, lease vencido; clasificación HTTP, timeouts, URL de `deauthorize`; mantenimiento sin polling y recuperación limitada. Las estadísticas semanales y mensuales (`tests/test_analytics.py`, `tests/test_services.py`) siguen pasando.

## 9. Migraciones

`0013_webhook_events`: solo aditiva. No borra ni reescribe datos, salvo marcar `initial_import_status='completed'` donde `history_synced_at` ya existe. La aplica automáticamente el `preDeployCommand` (`alembic upgrade head`) de `rudo-radar`.

## 10. Cambios de configuración en Railway (no aplicados; requieren tu acción)

1. **Ninguna variable de entorno nueva es obligatoria.** Los valores por defecto son seguros.
2. Despliega primero `rudo-radar` para que aplique la migración. `rudo-sync` toma el mismo código de la rama por defecto.
3. `rudo-sync` puede quedarse con `python -m app.cli`. Como los reintentos ya corren dentro de la app cada 60 s, se recomienda bajar la frecuencia a **una vez al día** (por ejemplo `17 9 * * *`). Mantener `0 */2 * * *` no hace polling: con la cola vacía no hace ninguna llamada a Strava.
4. `rudo-sync-daytime` y `rudo-sync-evening` ejecutan `true` una vez al año y no hacen nada. Pueden eliminarse cuando confirmes que no se necesitan.
5. Opcional: `LOG_LEVEL=INFO` (es el valor por defecto) para ver en los logs `strava_api_call` y `strava_webhook_event`.

## 11. Checklist de verificación del despliegue

- [ ] El deploy de `rudo-radar` aplica `0013_webhook_events` (aparece en los logs del pre-deploy).
- [ ] El log muestra `Strava webhook subscription ready: id=…`.
- [ ] `GET /admin/strava` responde con `subscription_id` distinto de null y `activity_polling: false`.
- [ ] Al crear una actividad de prueba en Strava aparece `strava_webhook_event … outcome=upserted` y `/admin/strava` cuenta un `/activities/:id`.
- [ ] Al renombrar la actividad aparece `outcome=updated_from_event`, sin una nueva llamada.
- [ ] Al borrar la actividad aparece `outcome=deleted`.
- [ ] La siguiente ejecución de `rudo-sync` imprime `"activity_polling": false` y `strava_api` sin `/athlete/activities`.
- [ ] `python -m app.cli status` muestra `unresolved: []` y `reauth_required: []` (o los atletas que deben reconectarse).
- [ ] Los paneles semanal y mensual muestran los mismos totales que antes del despliegue.
- [ ] Durante las primeras 48 h, revisar `/admin/strava` para confirmar que no hay eventos `failed` ni 429.

---

## 12. Text for the Strava Developer Team

> **Subject: Radar Rudo (App ID 25116) — API usage optimization completed**
>
> Hello Strava Developer Team,
>
> Thank you for the feedback on Radar Rudo. We have reworked the integration so that it uses webhooks for every ongoing update and calls the REST API only when a webhook cannot provide the data.
>
> **What changed**
>
> 1. **Periodic polling removed.** Previously, a scheduled job downloaded the last 21 days of activities for every connected athlete every two hours (about 240 requests per day for 10 athletes, almost all returning unchanged data). That job no longer reads activities. It only retries webhook events that previously failed with a transient error and revalidates club membership once per week per athlete.
> 2. **One-time historical import.** On an athlete's first authorization we import a bounded window of summary activities through `GET /athlete/activities` with 200 items per page and a hard page cap. The result and status of the import are recorded. Regular logins make no activity requests. The list endpoint is used again only if the athlete changes the private-activity scope, or reconnects after their credentials stopped working (and then only for the missing days).
> 3. **Webhook-driven updates.** Every push event is stored in a durable queue before we return HTTP 200, then processed asynchronously. Redelivered events are deduplicated, out-of-order and superseded events are skipped, deletions are applied locally, and title or type changes are applied directly from the event payload. We call `GET /activities/{id}` only for creations and for updates that the payload cannot describe. Events are acted on only after their `subscription_id` matches the subscription Strava reports for our app.
> 4. **Webhook security.** Because push events are not signed, payloads are strictly validated and destructive changes are never applied from the event alone. A deletion or privacy change is confirmed with a single `GET /activities/{id}` (only when the activity is stored locally). Rate limits, 5xx responses and timeouts are retried and never cause deletions.
> 5. **Deauthorization and privacy.** An `authorized=false` athlete event, once confirmed by Strava rejecting the athlete's credentials, deletes the athlete, their activities and their event records. Activities that become private are removed when the athlete has not granted `activity:read_all`. Account deletion revokes access through `POST /oauth/deauthorize`.
> 6. **Tokens and disconnections.** Tokens are encrypted at rest and refreshed shortly before expiry. A 401 triggers a single refresh and retry. A rejected refresh token marks the athlete as requiring re-authorization, excludes them from all further API calls and stops retries until they reconnect.
> 7. **Rate limits and resilience.** Rate-limit headers are recorded. Calls are deferred when usage reaches 90% of a limit, and on HTTP 429 all API calls pause until the 15-minute or daily window resets. Transient errors (5xx, timeouts) are retried with exponential backoff, up to six attempts. An admin diagnostics endpoint exposes API consumption by endpoint and any unprocessed events.
>
> **Expected impact:** with our current activity level (15–25 webhook events per day), daily API usage drops from roughly 240+ requests to about 20–30. Most of those are one `GET /activities/{id}` per new activity, plus at most 10 club-membership checks per week.
>
> We would be grateful if you could reconsider our request to increase the athlete capacity for Radar Rudo.
>
> Best regards,
> Radar Rudo team
