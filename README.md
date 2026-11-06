# TravelDesk

MVP funcional de una oficina privada de viajes, en español y pensada para móvil. Código independiente del proveedor de alojamiento. Sin LLM, claves de IA, rastreadores ni llamadas a terceros en el navegador.

## Arranque en tu ordenador

Requiere Python 3.13 o posterior. Abre una terminal en esta carpeta. En Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py init --demo
.\.venv\Scripts\python.exe app.py serve
```

La inicialización solicita tu usuario y una contraseña de al menos 12 caracteres, sin mostrarla. No existe una cuenta predeterminada en el código. Abre **http://127.0.0.1:8000** e inicia sesión con esas credenciales. Para volver a abrir la aplicación basta el último comando. `init` nunca reemplaza una base ya existente.

En macOS/Linux sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

La base persiste en `instance/traveldesk.sqlite`. `--demo` crea seis pasajeros ficticios con vuelos próximos, un tránsito previsto, un viaje terminado y distintos saldos. Las fechas se calculan al inicializar. Sin `--demo` se crea una oficina vacía.

## Qué puedes hacer

- **Resumen:** pasajeros activos, vuelos distintos en los próximos siete días, tránsito previsto, pendientes de cobro y reservas sin confirmar.
- **Pasajeros:** crear, buscar, editar, consultar historial y borrar una ficha junto con todas sus reservas y cobros, previa confirmación.
- **Reservas:** crear y editar pasajero, localizador, vuelo, aeropuertos, salida/llegada, escalas, estado e importe. Un localizador puede compartirse entre pasajeros; la combinación pasajero/localizador es única.
- **Calendario:** mes navegable en escritorio; agenda mensual en móvil. Pulsar una salida abre su reserva.
- **Estados:** pendiente/confirmada/cancelada son estados de reserva. Próximo/en tránsito/finalizado/cancelado son estados derivados de las fechas. No hay seguimiento de vuelos en tiempo real.
- **Cobros:** registrar cobros parciales, consultar saldos, filtrar pendientes y anular un registro erróneo con auditoría. No se procesan tarjetas ni se realizan transferencias o devoluciones reales. Una reserva cancelada conserva sus cobros para revisión.
- **Filtros:** texto, mes de salida, destino, estado de reserva o de viaje y saldo pendiente. Fechas de calendario y filtros en la zona del dispositivo.
- **Importación:** CSV UTF-8 con coma o punto y coma y Excel `.xlsx`, con vista previa, validación por fila, detección de duplicados y confirmación. El lote se guarda en una transacción; cualquier error bloquea todas las filas.
- **Privacidad:** ocultación visual de nombres/contactos, registro de actividad, cierre de sesión y bloqueo por inactividad.

## Importar desde Excel

Descarga la plantilla en la pantalla **Importar** o usa los ejemplos de `examples/`. El CSV también se puede abrir en Excel y guardar como `.xlsx`. Deben mantenerse estas columnas, en este orden:

```text
nombre,email,telefono,localizador,origen,destino,vuelo,salida,llegada,escalas,estado,importe,pagado
```

Una fila representa una reserva de un pasajero. `nombre`, `localizador`, `origen`, `destino`, `vuelo`, `salida`, `llegada`, `estado`, `importe` y `pagado` deben tener valores. Usa tres letras IATA distintas para origen y destino; fechas ISO con zona, por ejemplo `2026-11-05T10:00:00+01:00` o `2026-11-05T09:00:00Z`; importes como `850.00` sin símbolo, con punto decimal. Usa `0` si no hay cobros. Los teléfonos conviene mantenerlos como texto.

El importador agrupa por nombre/email sin distinguir mayúsculas ASCII. Si coinciden, reutiliza la ficha sin sobrescribir contactos. Revisa homónimos; no hay fusión automática avanzada ni asignación de columnas de un Excel arbitrario. Duplicados en el lote o ya guardados bloquean la confirmación. El cobro inicial importado queda con método «importación». Los libros con fórmulas se rechazan; pega valores antes de importar. No se admite `.xls`. Límite: 2 MB, 500 filas, 20 MB descomprimidos. La vista previa pertenece a la sesión, se puede usar una sola vez y caduca a los 10 minutos.

## Instalar en el teléfono

En producción debes usar **HTTPS**. Visita tu dominio desde el móvil e inicia sesión. En Android/Chrome usa **Instalar app** si aparece, o la opción de instalación del menú. En iPhone/Safari usa **Compartir → Añadir a pantalla de inicio**. El icono abrirá la app sin las barras del navegador.

La PWA almacena únicamente la interfaz y sus iconos. No ofrece consulta offline de pasajeros. Sin red no se guardan cambios ni se encolan cobros; se muestra un error. El indicador de conexión refleja la última petición, no una monitorización continua. La instalación nativa se debe verificar en el dispositivo de destino.

## Desplegar en un servidor privado con HTTPS

Se entrega una configuración Docker Compose con Waitress, SQLite persistente y Caddy como único punto de entrada. Requiere Docker con Compose, un dominio que apunte a tu servidor y puertos 80/443 disponibles. No se ha publicado ni contratado alojamiento; eliges dónde residirán los datos. Una web estática por sí sola no puede ejecutar este backend.

En el servidor Linux, dentro de esta carpeta:

```sh
export DOMAIN=viajes.tu-dominio.es
docker compose build
# Inicialización interactiva; no incluye datos ficticios en producción:
docker compose run --rm app python app.py init
docker compose up -d
```

Mantén `DOMAIN` definido en esa sesión o en un archivo `.env` del servidor (`DOMAIN=viajes.tu-dominio.es`, sin contraseñas). Caddy obtiene y renueva el certificado. El servicio de la aplicación no publica el puerto 8000 al exterior. Visita `https://viajes.tu-dominio.es`. Verifica inicio de sesión, cookie `Secure`, cabecera HSTS y subida de la plantilla antes de usar datos reales.

La autenticación de la app protege los datos; la pantalla de acceso sí es accesible desde Internet. Si necesitas que ni siquiera sea visible, sitúa el despliegue detrás de la VPN de la agencia. No actives `TRAVELDESK_PROXY=1` en un servicio expuesto directamente: solo confía en el proxy único de esta configuración. La configuración permite una agencia/administrador, no múltiples empresas ni permisos por empleado.

Para actualizar código: conserva el volumen `passengers`, haz copia y ejecuta `docker compose up -d --build`. No uses `docker compose down -v` sobre un despliegue con datos que quieras conservar. El MVP no incorpora migraciones de esquema automáticas.

### Alternativa sin Docker

Instala los requisitos en un entorno virtual, inicializa una base vacía y ejecuta Waitress mediante `python app.py serve`. Configura un proxy HTTPS hacia `127.0.0.1:8000` y arranque automático con el gestor de servicios de tu servidor. Define `TRAVELDESK_HTTPS=1`; si el proxy único envía `X-Forwarded-Proto`, define también `TRAVELDESK_PROXY=1`. El proceso debe tener acceso exclusivo a su directorio de datos. No utilices el servidor de desarrollo de Flask.

Variables disponibles:

| Variable | Función |
| --- | --- |
| `TRAVELDESK_DB` | Ruta del archivo SQLite; por defecto `instance/traveldesk.sqlite` |
| `TRAVELDESK_HTTPS=1` | Cookie Secure y HSTS; obligatorio para uso real |
| `TRAVELDESK_PROXY=1` | Confía en el protocolo enviado por un único proxy privado |
| `TRAVELDESK_USER`, `TRAVELDESK_PASSWORD` | Inicialización no interactiva opcional; usa un gestor de secretos y elimina la contraseña del entorno tras inicializar |

## Copias de seguridad y recuperación

La herramienta usa la API de backup de SQLite para obtener una copia consistente incluso con el servidor activo. No copies a mano solo el `.sqlite` abierto: pueden existir archivos WAL pendientes.

```powershell
.\.venv\Scripts\python.exe backup.py instance/traveldesk.sqlite copias/2026-10-30.sqlite
```

La copia verifica integridad, no sobrescribe destinos y elimina sesiones y vistas previas. **Contiene los contactos, reservas y cobros**: guárdala en disco cifrado, con acceso restringido y una política de retención. En Docker puedes ejecutar la copia dentro del servicio y extraerla:

```sh
docker compose cp backup.py app:/tmp/backup.py
docker compose exec app python /tmp/backup.py /data/traveldesk.sqlite /data/copia.sqlite
docker compose cp app:/data/copia.sqlite ./copia.sqlite
```

El nombre del destino debe ser nuevo en cada ejecución. Retira las copias del volumen de trabajo tras archivarlas de forma protegida. Para restaurar, detén la aplicación, conserva la base actual como respaldo y sustituye el archivo por la copia con el usuario detenido y sin archivos WAL/SHM antiguos. En Docker: `docker compose stop app`, usa `docker compose run --rm app` para operar sobre `/data` con el mismo usuario, y vuelve a arrancar. Ensaya la restauración en un entorno separado antes de depender de ella. La restauración recupera datos borrados que estén en la copia: aplica también tu política de eliminación a las copias.

Para cambiar una contraseña con acceso al servidor:

```sh
python app.py password
# O, en Docker:
docker compose exec app python app.py password
```

Solicita y confirma la nueva contraseña, y revoca todas las sesiones.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q -c pytest.ini
```

Pruebas de acceso, CSRF, origen, cookies, caducidad, bloqueo de intentos, altas/edición/borrado, centavos exactos, sobrecobro, estados en límites horarios, importación CSV/XLSX, fórmulas, duplicados, atomicidad, tokens de vista previa, límites, inyección SQL y cabeceras. Consulta `VALIDATION.md` para los resultados y las comprobaciones visuales realizadas en esta entrega.

## Decisiones y límites del MVP

- Un único administrador por agencia, una moneda (EUR), sin registro público ni recuperación por email. El acceso al servidor permite recuperar la contraseña.
- Un vuelo/itinerario por reserva; las escalas son un resumen textual. No hay múltiples segmentos editables, inventario de asientos, emisión de billetes ni conexión a aerolíneas.
- Dinero almacenado en céntimos enteros. No se calculan márgenes, impuestos, cambio de divisa ni facturas.
- Fechas almacenadas en UTC, introducidas y mostradas en la zona del dispositivo. No se deducen zonas horarias a partir de aeropuertos.
- SQLite con transacciones y claves foráneas es adecuado para este pequeño uso. No desplegar múltiples réplicas sobre el mismo archivo de red.
- Las alertas son avisos dentro del dashboard. No hay notificaciones push, emails ni tareas programadas.
- El servidor guarda datos sin cifrado de aplicación: el cifrado de disco y copias corresponde al despliegue. No se afirma certificación ni cumplimiento legal automático.
- Auditoría básica (últimas 200 acciones visibles), sin nombres/contactos; no es un registro inmutable. Define conservación y mantenimiento en la agencia.
- No se han introducido datos reales. El usuario debe completar su revisión operativa y de privacidad antes de usarlos.

Estructura: `app.py` API y validación; `static/` interfaz y PWA; `tests/` pruebas; `examples/` plantillas; `Dockerfile`, `compose.yaml`, `Caddyfile` despliegue; `backup.py` copia consistente. Las dependencias se fijan en requirements y las transitivas verificadas en `constraints.txt`.
