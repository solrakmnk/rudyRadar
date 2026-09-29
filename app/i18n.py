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
        "this_week": "Esta semana", "this_month": "Este mes", "last_month": "Mes pasado", "friendly_ranking": "Ranking amistoso", "live": "EN VIVO", "no_activity": "Aún sin actividad",
        "logout": "Salir ↗", "on_radar": "EN EL RADAR", "team_moving": "RUD@S EN MOVIMIENTO", "last_sync": "Última sincronización", "pending": "pendiente",
        "verified_members": "Solo miembros verificados de RUD@S.", "sync_ready": "Sincronización lista", "reviewed_activities": "{count} actividades revisadas",
        "welcome": "Qué onda,", "kilometers_counting": "Los kilómetros ya están contando para el equipo.", "something_wrong": "Algo se cruzó en el camino", "back": "Volver",
        "not_member_title": "Rudy todavía no te encuentra en RUD@S 👀", "not_member_text": "Radar Rudo es exclusivo para miembros del club RUD@S en Strava.",
        "privacy_title": "Privacidad de Radar Rudo", "privacy_intro": "Radar Rudo usa la conexión autorizada con Strava para crear métricas privadas de RUD@S.",
        "privacy_data_title": "Datos que guardamos", "privacy_data_text": "Guardamos tu identificador de Strava, nombre, foto de perfil, tokens cifrados y resúmenes de actividad: deporte, fecha, distancia, duración, desnivel, velocidad, calorías y métricas de esfuerzo cuando Strava las entrega. Conservamos hasta un año de estos resúmenes para comparaciones históricas. No guardamos GPS, polylines, rutas ni secuencias biométricas.",
        "privacy_use_title": "Cómo los usamos", "privacy_use_text": "Los usamos para verificar tu pertenencia a RUD@S, sincronizar actividades y mostrar tu panel y rankings internos. No vendemos datos ni los usamos para publicidad.",
        "privacy_control_title": "Control y eliminación", "privacy_control_text": "Puedes revocar Radar Rudo desde Strava. También puedes borrar tu información desde el panel; al hacerlo se eliminan actividades y tokens locales. Los webhooks procesan la revocación de Strava.",
        "privacy_retention_title": "Conservación y contacto", "privacy_retention_text": "Conservamos los datos mientras mantengas autorizada la aplicación. Para solicitudes de privacidad contacta al administrador de RUD@S.",
        "delete_data": "Eliminar mi cuenta de Radar Rudo y mis datos", "delete_confirm": "Se eliminará tu cuenta de Radar Rudo, tus datos locales y la autorización de esta app. Tu cuenta y actividades de Strava no se borrarán. Para regresar deberás conectar Strava otra vez.",
        "data_deleted": "Tu cuenta y datos de Radar Rudo fueron eliminados.", "powered_by": "Compatible con Strava",
        "weekly_pulse": "PULSO SEMANAL", "vs_last_week": "vs. semana pasada", "more_distance": "más kilómetros", "less_distance": "menos kilómetros", "same_distance": "mismo kilometraje", "period_stories": "Historias del periodo", "your_summary": "TU RESUMEN", "total_period": "Total del periodo", "swim": "Natación", "open_water": "Aguas abiertas", "bike": "Bici", "run": "Carrera", "strength": "Fuerza", "wellbeing": "Bienestar", "your_longest_day": "Tu día con más distancia", "your_busiest_day": "Tu día con más actividad", "team_busiest_day": "El día que más se movió RUD@S", "team_discipline_days": "Los grandes días del equipo", "participants": "participantes", "sessions": "sesiones", "gym": "Gym", "no_story_yet": "La próxima actividad abre la historia de este periodo.", "weekday_0": "Lunes", "weekday_1": "Martes", "weekday_2": "Miércoles", "weekday_3": "Jueves", "weekday_4": "Viernes", "weekday_5": "Sábado", "weekday_6": "Domingo",
    },
    "en": {
        "product": "Radar Rudo", "assistant": "Rudy finds the stories.", "connect": "Connect with Strava",
        "privacy": "Privacy", "language_es": "ES", "language_en": "EN", "club_moving": "THE CLUB IN MOTION",
        "hero": "Your kilometers already tell a story.", "intro": "Connect Strava. Rudy finds the team's rhythm, recognizes consistency, and finds the stories behind every workout.",
        "exclusive": "Only for RUD@S.", "activities": "Activities", "distance": "Distance", "active_days": "Active days", "elevation": "Elevation",
        "this_week": "This week", "this_month": "This month", "last_month": "Last month", "friendly_ranking": "Friendly ranking", "live": "LIVE", "no_activity": "No activity yet",
        "logout": "Leave ↗", "on_radar": "ON THE RADAR", "team_moving": "RUD@S IN MOTION", "last_sync": "Last sync", "pending": "pending",
        "verified_members": "Only verified RUD@S members.", "sync_ready": "Sync complete", "reviewed_activities": "{count} activities reviewed",
        "welcome": "What's up,", "kilometers_counting": "Your kilometers are already counting for the team.", "something_wrong": "Something got in the way", "back": "Back",
        "not_member_title": "Rudy cannot find you in RUD@S yet 👀", "not_member_text": "Radar Rudo is only for RUD@S club members on Strava.",
        "privacy_title": "Radar Rudo privacy", "privacy_intro": "Radar Rudo uses your authorized Strava connection to create private RUD@S metrics.",
        "privacy_data_title": "Data we store", "privacy_data_text": "We store your Strava identifier, name, profile image, encrypted tokens, and activity summaries: sport, date, distance, duration, elevation, speed, calories, and effort metrics when supplied by Strava. We retain up to one year of these summaries for historical comparisons. We do not store GPS, polylines, routes, or biometric streams.",
        "privacy_use_title": "How we use it", "privacy_use_text": "We use it to verify RUD@S membership, sync activities, and show your dashboard and internal rankings. We do not sell data or use it for advertising.",
        "privacy_control_title": "Control and deletion", "privacy_control_text": "You can revoke Radar Rudo from Strava. You can also delete your information from the dashboard; this removes local activities and tokens. Webhooks process Strava revocation.",
        "privacy_retention_title": "Retention and contact", "privacy_retention_text": "We retain data while you authorize the application. Contact the RUD@S administrator for privacy requests.",
        "delete_data": "Delete my Radar Rudo account and data", "delete_confirm": "Your Radar Rudo account, local data, and this app authorization will be deleted. Your Strava account and activities will not be deleted. You will need to connect Strava again to return.",
        "data_deleted": "Your Radar Rudo account and local data were deleted.", "powered_by": "Compatible with Strava",
        "weekly_pulse": "WEEKLY PULSE", "vs_last_week": "vs. last week", "more_distance": "more kilometers", "less_distance": "fewer kilometers", "same_distance": "same distance", "period_stories": "Stories from this period", "your_summary": "YOUR SUMMARY", "total_period": "Period total", "swim": "Pool swim", "open_water": "Open water", "bike": "Bike", "run": "Run", "strength": "Strength", "wellbeing": "Wellbeing", "your_longest_day": "Your longest-distance day", "your_busiest_day": "Your busiest day", "team_busiest_day": "RUD@S's busiest day", "team_discipline_days": "The team's biggest days", "participants": "participants", "sessions": "sessions", "gym": "Gym", "no_story_yet": "Your next activity starts this period's story.", "weekday_0": "Monday", "weekday_1": "Tuesday", "weekday_2": "Wednesday", "weekday_3": "Thursday", "weekday_4": "Friday", "weekday_5": "Saturday", "weekday_6": "Sunday",
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
