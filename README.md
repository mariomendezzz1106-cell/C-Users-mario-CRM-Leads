# CRM de Leads · plataforma SaaS

Aplicación web multiempresa con Flask y PostgreSQL. Reutiliza el motor de lead scoring (capa 1), el
análisis con IA (capa 2) y los informes (capa 3) del proyecto original, y conserva el diseño del panel.

**Cómo arrancarlo, probarlo y publicarlo:** [GUIA_POWERSHELL.md](GUIA_POWERSHELL.md)

## Funcionalidades
- **Dashboard**: leads HOT sin atender, embudo abierto y ponderado, ganado, tareas vencidas, próximos cierres y actividad.
- **Leads**: el panel original (resumen por clase, conclusión, búsqueda, ficha con desglose, correo y seguimiento), con alta, edición, borrado, importación CSV/Excel, conversión en oportunidad y análisis con IA.
- **Clientes y contactos**: crear, editar, borrar, buscar y filtrar por sector y tipo. La ficha muestra contactos, oportunidades, tareas e historial.
- **Embudo**: kanban por etapas; las tarjetas se mueven con un desplegable o arrastrándolas.
- **Oportunidades**: importe, probabilidad, ponderado, cierre y responsable, con filtros.
- **Tareas**: vencimiento, prioridad, asignación; se marcan como hechas.
- **Inteligencia artificial**: análisis de un lead, conclusión de la cartera y preguntas sobre tus datos, con llamadas reales a la API de Claude.
- **Informes**: tablas por clase, origen, sector, responsable y usuario. Descargas: Excel, informe, CSV para HubSpot, oportunidades y clientes.
- **Ajustes**: datos de la empresa, usuarios y roles, cambio de contraseña y cierre de otras sesiones.

## Seguridad
- Contraseñas con **Argon2id**. Cookie de sesión firmada, `HttpOnly`, `SameSite=Lax` y `Secure` en producción, con caducidad de 8 h.
- Sesiones invalidables: cambiar la contraseña o quitar el acceso las cierra al momento.
- Límite de intentos de login (5 por email y 30 por IP cada 15 min). Token CSRF en formularios y API.
- **Separación por empresa**: todas las tablas llevan `org_id` y cada consulta filtra por la empresa del usuario. Las referencias cruzadas entre empresas se rechazan.
- Roles: solo lectura, comercial, administrador y propietario.
- Cabeceras CSP, HSTS (en producción), `X-Frame-Options` y `nosniff`. Ningún secreto en el código: todo va en variables de entorno.

## Estructura
| Ruta | Qué es |
|---|---|
| `crm/` | Aplicación: `ajustes.py`, `modelos.py`, `servicios.py`, `auth.py`, `api.py`, `ia.py` |
| `plantillas/app.html`, `static/crm.js`, `static/crm.css` | Frontend (mismo diseño que el panel) |
| `plantillas/login.html`, `registro.html` | Acceso |
| `capa1_motor.py`, `reglas.py` | Motor de scoring (sin cambios) |
| `capa3_salidas.py` | Excel, informe y CSV de HubSpot (sin cambios) |
| `capa2_ia/`, `capa2_api.py` | Instrucciones de la IA y script por lotes original |
| `app.py` | Arranque local (Windows, Waitress) |
| `wsgi.py` | Arranque en producción (gunicorn) |
| `manage.py` | `init-db`, `crear-empresa`, `importar-sqlite` |
| `render.yaml`, `Dockerfile` | Despliegue |
| `tests/` | 16 pruebas contra PostgreSQL |
| `legado/` | Versión anterior con SQLite, como referencia |
| `plantillas/panel.html` | Panel original de un solo archivo (lo sigue generando `capa3_salidas.py`) |

## Pipeline original (sigue funcionando)
```powershell
.\.venv\Scripts\python.exe main.py --fecha-ref 2026-11-23
```
