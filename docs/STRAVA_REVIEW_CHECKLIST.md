# Radar Rudo — preparación para revisión de Strava

Actualizado: 4 de octubre de 2026.

## Resumen para la solicitud

- **Aplicación:** Radar Rudo
- **URL:** https://rudo-radar.up.railway.app/
- **Audiencia actual:** integrantes verificados del club RUD@S.
- **Objetivo:** ayudar a cada atleta a entender su constancia y rendimiento por disciplina a partir de sus actividades autorizadas.
- **OAuth:** el registro solicita `read`, `profile:read_all` y `activity:read`; `activity:read_all` es opcional y se habilita después desde Configuración.
- **Webhook:** activo en `https://rudo-radar.up.railway.app/webhooks/strava`; procesa altas, cambios, eliminaciones y revocaciones. El cron de reconciliación corre cada dos horas.
- **Retención actual:** hasta un año de resúmenes; no se almacenan rutas, GPS, polylines ni streams biométricos. La retención supera el máximo de siete días descrito en la política vigente y debe corregirse o autorizarse expresamente antes de solicitar revisión.
- **Eliminación:** el usuario puede eliminar su cuenta desde Configuración; se revoca el acceso y se borran atleta, tokens y actividades locales. La revocación recibida por webhook también elimina los datos.
- **Contacto:** solrak.m@gmail.com

## Bloqueador de revisión

La API Policy vigente desde el 1 de junio de 2026 contiene tres incompatibilidades centrales con el producto actual:

1. La sección 2.3 indica que los datos proporcionados por un usuario solo pueden mostrarse a ese mismo usuario y que no deben mostrarse datos de otros usuarios, aunque sean públicos en Strava.
2. La sección 5.4 prohíbe procesar datos de Strava, incluso agregados o desidentificados, para analítica, análisis o generación de insights.
3. Las secciones 6.2 y 6.4 limitan el caché a siete días y restringen la conservación adicional. Radar conserva resúmenes durante un año para comparaciones históricas.

Radar Rudo actualmente muestra a otros integrantes:

- nombres y fotografías en rankings;
- totales individuales por disciplina;
- participantes de cada disciplina;
- perfiles comparativos de otros atletas;
- totales y tendencias del equipo derivados de varios atletas.

Estas funciones y la retención anual son el principal riesgo de rechazo. Antes de enviar la solicitud se necesita una confirmación escrita de Strava de que el caso de uso privado del club, los agregados y la retención histórica están permitidos, o una modalidad que muestre únicamente datos del atleta autenticado y conserve como máximo siete días. El consentimiento interno del club no reemplaza estas reglas.

## Estado de cumplimiento

| Requisito | Estado | Evidencia o acción |
|---|---|---|
| Capacidad actual de 10 atletas | Listo para solicitar ampliación | La documentación indica que la revisión corresponde al alcanzar 10 conexiones. |
| Webhooks y revocación | Cumple | Suscripción activa; procesamiento asíncrono e idempotente. |
| Evitar polling excesivo | Cumple | Webhook principal y reconciliación cada dos horas. |
| Permisos mínimos | Cumple | `activity:read` por defecto; privadas optativas mediante `activity:read_all`. |
| Política de privacidad pública | Implementado | `/privacy`, disponible en español e inglés. |
| Eliminación por solicitud o revocación | Implementado | Configuración de cuenta y webhook de desautorización. |
| Confirmación de eliminación | Implementado | Mensaje visible después de borrar la cuenta. |
| Contacto de soporte visible | Implementado | Correo en la política de privacidad. |
| Seguridad | Implementado | Tokens cifrados, secretos fuera del repositorio y sesiones seguras en HTTPS. |
| Branding oficial | Pendiente | Sustituir o complementar los CTA de OAuth con el recurso oficial “Connect with Strava”; revisar la atribución “Compatible with Strava”. |
| Visualización limitada al usuario autenticado | **No cumple actualmente** | Rankings, perfiles y panel del equipo muestran datos de otros atletas. |
| Analítica agregada | **No cumple actualmente** | Totales del equipo, rankings, historias y comparativos se derivan de datos de varios atletas; revisar sección 5.4. |
| Retención máxima de siete días | **No cumple actualmente** | El producto conserva un año para comparaciones históricas; revisar secciones 6.2 y 6.4. |
| Acceso del usuario a los datos recopilados | Parcial | El panel muestra resúmenes; documentar el proceso de exportación o entrega bajo solicitud. |
| Enlace a la cuenta de Strava | Implementado | Configuración incluye un enlace directo a las aplicaciones conectadas de Strava. |
| Aviso de monitoreo de uso | Implementado | La política de privacidad informa que Strava puede monitorear datos de uso de la API. |

## Capturas para la solicitud

Preparar capturas en español e inglés, escritorio y móvil, sin secretos ni URLs de OAuth con códigos:

1. Landing completa y CTA de conexión.
2. Pantalla de consentimiento previa que explica actividades visibles y privadas opcionales.
3. Autorización de Strava con los scopes solicitados.
4. Dashboard personal por disciplina.
5. Configuración de cuenta y control de actividades privadas.
6. Política de privacidad y correo de soporte.
7. Flujo de eliminación y confirmación final.
8. Cualquier pantalla que muestre datos derivados de Strava, incluidos rankings y participantes si Strava autoriza expresamente ese diseño.

## Texto sugerido del caso de uso

> Radar Rudo es un panel privado para atletas verificados del club RUD@S. Importa los resúmenes de actividad que cada atleta autoriza para ayudarle a revisar su constancia y rendimiento por disciplina. Solicita acceso de solo lectura a actividades visibles por defecto; el acceso a actividades privadas es separado, opcional y revocable. No almacenamos rutas, GPS, polylines ni streams biométricos. Usamos webhooks para altas, cambios, eliminaciones y revocaciones, y una reconciliación cada dos horas como respaldo. Los usuarios pueden eliminar su cuenta y todos sus datos locales desde la aplicación.

No enviar este texto todavía como declaración de cumplimiento. Primero deben resolverse por escrito con Strava las secciones 2.3, 5.4, 6.2 y 6.4, o eliminar del producto los rankings, agregados, perfiles cruzados e histórico mayor a siete días.

## Fuentes oficiales

- API Agreement: https://www.strava.com/legal/api
- API Policy: https://www.strava.com/legal/api_policy
- Brand Guidelines: https://developers.strava.com/guidelines/
- Rate limits y revisión: https://developers.strava.com/docs/rate-limits/
- Webhooks: https://developers.strava.com/docs/webhooks/
- Authentication: https://developers.strava.com/docs/authentication/
- API reference: https://developers.strava.com/docs/reference/
