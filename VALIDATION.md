# Validación de la entrega

Fecha: 30 de octubre de 2026. Datos de demostración exclusivamente.

## Pruebas automáticas

Entorno: Windows, Python 3.13, Flask 3.1.3, SQLite integrado en Python, openpyxl 3.1.5, pytest 9.2.0. Dependencias instaladas en un entorno virtual aislado.

Resultado: **29 pruebas superadas**. Comando ejecutado desde la carpeta de la aplicación:

```text
python -m pytest -q -c pytest.ini --basetemp ../../work/test-final --tb=short
29 passed in 8.78s
```

La opción `--basetemp` se utilizó para mantener archivos temporales dentro del espacio de trabajo; en una instalación normal basta `python -m pytest -q -c pytest.ini`.

Cobertura funcional:

| Área | Comprobaciones |
| --- | --- |
| Acceso | API sin sesión, cierre de sesión, caducidad absoluta e inactividad |
| Protección | CSRF, Origin, peticiones cross-site, cookie Secure/HttpOnly/SameSite, HSTS, CSP, no-store |
| Credenciales | Bloqueo persistente tras cinco intentos fallidos |
| Pasajeros | Alta, edición, borrado con reservas/cobros en cascada, persistencia entre instancias |
| Reservas | Unicidad pasajero/localizador, IATA, fechas con zona, llegada posterior, importe y estados válidos |
| Cobros | Céntimos exactos, parciales, bloqueo de sobrecobro, anulación, bloqueo en canceladas |
| Tránsito | Instantes inmediatamente anteriores, iguales y posteriores a salida/llegada |
| Importación | CSV, XLSX, fórmulas rechazadas, vista previa sin escritura de registros finales |
| Integridad | Duplicados, fila inválida bloquea todo el lote, conflicto posterior revierte pasajeros y reservas |
| Tokens | Vista previa ligada a la sesión, caducidad, un solo uso |
| Límites | Tamaño del cuerpo, longitud, formato JSON, rutas que no sirven archivos privados |
| Copias | Copia consistente, integridad SQLite, eliminación de sesiones y vistas previas en la copia |
| Inyección | Una cadena con SQL se almacena como texto sin ejecutar instrucciones |

Comprobaciones adicionales: sintaxis JavaScript de `app.js` y `sw.js`, compilación Python y `pip check` sin errores. `docker compose config --quiet` validó la configuración con un dominio de prueba; el cliente emitió un aviso de lectura de su configuración global de credenciales, ajeno al archivo del proyecto.

## Pruebas en navegador

Se utilizó el navegador integrado, con servidor Waitress real en loopback y base de prueba fuera de la carpeta de entrega.

- Inicio de sesión con cuenta ficticia.
- Alta de «Ana Prueba» y aparición inmediata en la lista de pasajeros.
- Creación de reserva `QA001`, MAD → BOG, fechas del 15 de noviembre de 2026, importe 100,25 €.
- Búsqueda por localizador y apertura del detalle desde la lista móvil.
- Registro de cobro de 30,10 € y verificación visual del saldo de 70,15 €.
- Calendario móvil como agenda, cambio octubre → noviembre, aparición del viaje creado.
- Revisión visual a 390 × 844 y 1440 × 1000. En móvil las reservas usan tarjetas, con acceso a detalle y saldo, sin necesitar desplazamiento horizontal.
- Capturas entregadas como `traveldesk-mobile.jpg` y `traveldesk-desktop.jpg`, junto al ZIP de código.

Las pruebas de navegador descritas fueron ejecutadas durante la construcción; no se entrega una suite Playwright automática. La suite reproducible incluida prueba la API y la lógica del servidor.

## Pendiente en el entorno de destino

- No se construyó ni arrancó la imagen Docker; se validó la configuración Compose.
- No se ha desplegado un dominio, obtenido un certificado ni probado el proxy en un servidor público.
- No se ha instalado la PWA en un Android/iPhone físico ni comprobado su comportamiento con el navegador del destinatario.
- No se ha realizado una auditoría de seguridad externa, prueba de carga o revisión legal.
- El bloqueo de interfaz por 15 minutos y la desconexión del teléfono requieren una prueba prolongada en el dispositivo final. La caducidad del servidor sí tiene pruebas automatizadas.

Antes del uso real: inicializa una base vacía, configura HTTPS, verifica cookies seguras y restauración de copias, instala en el móvil y ejecuta una importación ficticia. El README describe estos pasos y las decisiones del MVP.
