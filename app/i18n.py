from __future__ import annotations

from collections.abc import Mapping

SUPPORTED_LOCALES = {"es", "en"}
DEFAULT_LOCALE = "es"

MESSAGES: dict[str, dict[str, str]] = {
    "es": {
        "product": "Radar Rudo", "assistant": "Rudy encuentra las historias.", "connect": "Conectar con Strava",
        "privacy": "Privacidad", "language_es": "ES", "language_en": "EN", "club_moving": "EL CLUB EN MOVIMIENTO",
        "hero": "Tus kilómetros ya cuentan una historia.", "intro": "Conecta Strava. Rudy encuentra el ritmo del equipo, reconoce la constancia y encuentra las historias detrás de cada entrenamiento.",
        "exclusive": "Exclusivo para RUD@S.", "activities": "Actividades", "distance": "Distancia", "active_days": "Días activos", "elevation": "Desnivel",
        "this_week": "Esta semana", "this_month": "Este mes", "friendly_ranking": "Ranking amistoso", "live": "EN VIVO", "no_activity": "Aún sin actividad",
        "logout": "Salir ↗", "on_radar": "EN EL RADAR", "team_moving": "RUD@S EN MOVIMIENTO", "last_sync": "Última sincronización", "pending": "pendiente",
        "verified_members": "Solo miembros verificados de RUD@S.", "sync_ready": "Sincronización lista", "reviewed_activities": "{count} actividades revisadas",
        "welcome": "Qué onda,", "kilometers_counting": "Los kilómetros ya están contando para el equipo.", "something_wrong": "Algo se cruzó en el camino", "back": "Volver",
        "not_member_title": "Rudy todavía no te encuentra en RUD@S 👀", "not_member_text": "Radar Rudo es exclusivo para miembros del club RUD@S en Strava.",
        "privacy_title": "Privacidad de Radar Rudo", "privacy_intro": "Radar Rudo usa la conexión autorizada con Strava para crear métricas privadas de RUD@S.",
        "privacy_data_title": "Datos que guardamos", "privacy_data_text": "Guardamos tu identificador de Strava, nombre, foto de perfil, tokens cifrados y resúmenes de actividad: deporte, fecha, distancia, duración, desnivel, velocidad, calorías y métricas de esfuerzo cuando Strava las entrega. No guardamos GPS, polylines, rutas ni secuencias biométricas.",
        "privacy_use_title": "Cómo los usamos", "privacy_use_text": "Los usamos para verificar tu pertenencia a RUD@S, sincronizar actividades y mostrar tu panel y rankings internos. No vendemos datos ni los usamos para publicidad.",
        "privacy_control_title": "Control y eliminación", "privacy_control_text": "Puedes revocar Radar Rudo desde Strava. También puedes borrar tu información desde el panel; al hacerlo se eliminan actividades y tokens locales. Los webhooks procesan la revocación de Strava.",
        "privacy_retention_title": "Conservación y contacto", "privacy_retention_text": "Conservamos los datos mientras mantengas autorizada la aplicación. Para solicitudes de privacidad contacta al administrador de RUD@S.",
        "delete_data": "Borrar mis datos", "delete_confirm": "¿Eliminar tus actividades y tokens locales? Esta acción no se puede deshacer.",
        "data_deleted": "Tus datos locales fueron eliminados.", "powered_by": "Compatible con Strava",
    },
    "en": {
        "product": "Radar Rudo", "assistant": "Rudy finds the stories.", "connect": "Connect with Strava",
        "privacy": "Privacy", "language_es": "ES", "language_en": "EN", "club_moving": "THE CLUB IN MOTION",
        "hero": "Your kilometers already tell a story.", "intro": "Connect Strava. Rudy finds the team's rhythm, recognizes consistency, and finds the stories behind every workout.",
        "exclusive": "Only for RUD@S.", "activities": "Activities", "distance": "Distance", "active_days": "Active days", "elevation": "Elevation",
        "this_week": "This week", "this_month": "This month", "friendly_ranking": "Friendly ranking", "live": "LIVE", "no_activity": "No activity yet",
        "logout": "Leave ↗", "on_radar": "ON THE RADAR", "team_moving": "RUD@S IN MOTION", "last_sync": "Last sync", "pending": "pending",
        "verified_members": "Only verified RUD@S members.", "sync_ready": "Sync complete", "reviewed_activities": "{count} activities reviewed",
        "welcome": "What's up,", "kilometers_counting": "Your kilometers are already counting for the team.", "something_wrong": "Something got in the way", "back": "Back",
        "not_member_title": "Rudy cannot find you in RUD@S yet 👀", "not_member_text": "Radar Rudo is only for RUD@S club members on Strava.",
        "privacy_title": "Radar Rudo privacy", "privacy_intro": "Radar Rudo uses your authorized Strava connection to create private RUD@S metrics.",
        "privacy_data_title": "Data we store", "privacy_data_text": "We store your Strava identifier, name, profile image, encrypted tokens, and activity summaries: sport, date, distance, duration, elevation, speed, calories, and effort metrics when supplied by Strava. We do not store GPS, polylines, routes, or biometric streams.",
        "privacy_use_title": "How we use it", "privacy_use_text": "We use it to verify RUD@S membership, sync activities, and show your dashboard and internal rankings. We do not sell data or use it for advertising.",
        "privacy_control_title": "Control and deletion", "privacy_control_text": "You can revoke Radar Rudo from Strava. You can also delete your information from the dashboard; this removes local activities and tokens. Webhooks process Strava revocation.",
        "privacy_retention_title": "Retention and contact", "privacy_retention_text": "We retain data while you authorize the application. Contact the RUD@S administrator for privacy requests.",
        "delete_data": "Delete my data", "delete_confirm": "Delete your local activities and tokens? This cannot be undone.",
        "data_deleted": "Your local data was deleted.", "powered_by": "Compatible with Strava",
    },
}


def translate(locale: str, key: str, **values: object) -> str:
    message = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE]).get(key, MESSAGES[DEFAULT_LOCALE].get(key, key))
    return message.format(**values)


def preferred_locale(query_locale: str | None, session: Mapping[str, object]) -> str:
    if query_locale in SUPPORTED_LOCALES:
        return query_locale
    saved = session.get("locale")
    return saved if saved in SUPPORTED_LOCALES else DEFAULT_LOCALE
