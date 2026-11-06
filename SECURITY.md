# Seguridad y operación

## Controles implementados

- Todas las rutas de datos requieren una sesión. No hay contraseñas predeterminadas ni alta pública. Un único administrador tiene permisos sobre toda la agencia.
- Contraseña derivada con scrypt de Werkzeug; token aleatorio de sesión de 48 bytes, solo su SHA-256 en base de datos. Cookie HttpOnly, SameSite Strict, y Secure en modo HTTPS.
- Caducidad absoluta de 8 horas; inactividad del servidor de 30 minutos. La interfaz bloquea tras 15 minutos sin interacción, también si no hay red. Guarda únicamente una marca de bloqueo en sessionStorage, sin datos de pasajeros. Sin conexión, la cookie no puede revocarse en el servidor hasta recuperar red o caducar; los datos visibles se limpian inmediatamente.
- Tras 5 fallos de acceso se bloquean los intentos 5 minutos, de forma persistente y global para la cuenta. Esta simplicidad permite que un atacante provoque bloqueos temporales: restringe el acceso con una VPN si procede.
- CSRF por sesión en cabecera, comprobación de Origin cuando está presente, rechazo de peticiones cross-site y de cuerpos no JSON (salvo subida multipart).
- Consultas SQL parametrizadas, validación de campos, importes en enteros, bloqueo de sobrecobro mediante transacción de escritura.
- CSP sin scripts ni estilos inline, protección contra marcos, política de referencias, no-store en respuestas y desactivación de permisos de cámara/micrófono/geolocalización.
- Service worker limitado a la interfaz. Las rutas `/api/` nunca se cachean. Los datos no se escriben en localStorage, IndexedDB ni CacheStorage.
- XLSX limitado en tamaño comprimido/descomprimido; fórmulas rechazadas. Importación con tokens aleatorios de una sola vez, ligados a la sesión y con vencimiento.
- Auditoría sin contenido de fichas; eliminaciones en cascada y anulación de cobros registradas. Se evita registrar cuerpos y credenciales en logs del servidor.

## Responsabilidades del despliegue

Usa HTTPS, contraseñas únicas, permisos del sistema limitados, disco y backups cifrados. El proceso y los administradores del servidor pueden leer la base. Actualiza dependencias y sistema. No expongas SQLite ni copias mediante un servidor estático. No uses CORS abierto. No uses proxies adicionales sin revisar la confianza en cabeceras.

Esta versión no incluye MFA, roles, aislamiento entre agencias, antivirus de ficheros, registro inmutable ni cifrado por campo. Evita pasaportes, documentos, datos de salud o tarjetas. El registro de cobros no necesita números de tarjeta.

Las vistas previas caducadas se limpian en la siguiente importación y al caducar/revocar sesiones durante el uso. Si necesitas borrado físico a una hora exacta, configura mantenimiento en tu servidor. Las páginas ya abiertas mantienen datos en memoria hasta cierre/bloqueo; la instalación no equivale a protección del dispositivo. Protege el móvil con bloqueo y evita dispositivos compartidos.

SQLite puede conservar restos en páginas liberadas y copias anteriores. Para requisitos de borrado reforzado establece mantenimiento de base, cifrado y rotación de backups; el borrado lógico de la ficha no equivale a borrado forense del soporte.
