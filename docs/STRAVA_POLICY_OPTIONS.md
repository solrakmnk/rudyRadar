# Opciones para adaptar Radar Rudo a la política 2026 de Strava

Actualizado: 4 de octubre de 2026.

## Recomendación

Solicitar primero una respuesta escrita de Strava describiendo exactamente el producto actual. Mientras llega, preparar la opción A como modo de revisión. Así se puede presentar una versión que cumple con la lectura literal de la política sin borrar todavía el trabajo del dashboard comunitario.

## Opción A — modo personal para revisión

Cada atleta ve únicamente sus propios totales y comparaciones. Se ocultan rankings, perfiles de otros atletas, participantes por disciplina, historias y agregados del equipo. Las actividades se conservan como máximo siete días; el dashboard compara únicamente datos todavía presentes en esa ventana.

**Ventajas:** es la ruta con menor riesgo de rechazo según las secciones 2.3, 5.4 y 6.2. Conserva OAuth, sincronización, disciplinas, privacidad, exportación y eliminación.

**Costo:** pierde temporalmente el componente social y las comparaciones mensuales o anuales.

## Opción B — solicitar autorización expresa para el club

Enviar a `developers@strava.com` una descripción, capturas y preguntas cerradas sobre rankings internos, totales agregados, perfiles cruzados y retención histórica. No asumir que el consentimiento de los integrantes reemplaza la política.

**Ventajas:** si Strava lo autoriza por escrito, Radar conserva su propuesta actual.

**Costo:** la aprobación no está garantizada y no existe un plazo fijo. La solicitud de ampliación no debe afirmar cumplimiento mientras estas funciones sigan activas.

## Opción C — separar el panel personal de una competencia autodeclarada

Usar Strava solo para el panel privado de cada atleta. Para el tablero del equipo, cada integrante captura o confirma manualmente un total semanal independiente, o participa mediante una fuente que permita explícitamente clasificaciones compartidas. Los datos del tablero no se copiarían ni derivarían automáticamente de la API de Strava.

**Ventajas:** mantiene la motivación comunitaria y separa claramente el uso restringido de Strava.

**Costo:** agrega fricción y requiere diseñar validación para evitar errores o cifras falsas.

## Histórico personal

Para cumplir literalmente el límite de siete días, las comparaciones de meses y años no deben construirse desde datos de Strava almacenados por Radar. Las alternativas son:

1. solicitar a Strava autorización expresa para una retención mayor;
2. limitar el producto a una ventana móvil de siete días;
3. permitir que el usuario aporte datos por una vía independiente cuyos términos admitan almacenamiento histórico.

Anonimizar, agregar o convertir las actividades en métricas no resuelve por sí solo el problema: la sección 5.4 también cubre datos derivados y agregados.

## Preguntas concretas para Strava

1. ¿Puede una aplicación privada de un club mostrar a miembros autenticados rankings y totales de otros miembros que autorizaron expresamente esa visualización?
2. ¿Puede conservar resúmenes sin rutas ni GPS por doce meses para comparaciones personales?
3. ¿Puede mostrar totales agregados del club sin actividades individuales, horarios ni rutas?
4. Si no, ¿aceptan un modo de revisión exclusivamente personal con caché máximo de siete días?
5. ¿Qué evidencia esperan para demostrar eliminación, revocación, exportación y funcionamiento de webhooks?
