# Guía con Windows PowerShell

Carpeta del proyecto: `C:\Users\mario\CRM-Leads`. Todos los comandos se escriben en PowerShell
desde esa carpeta. Usan el Python del entorno virtual (`.\.venv\Scripts\python.exe`), así que no
hace falta que `python` funcione suelto.

---

## 1. Arrancar el CRM en tu ordenador

PostgreSQL 17 ya está instalado como servicio de Windows (`postgresql-x64-17`) y arranca solo con el
equipo. La base `crm` y su usuario `crm_app` ya existen. La conexión y la clave de sesión están en `.env`.

```powershell
cd C:\Users\mario\CRM-Leads
```
```powershell
.\.venv\Scripts\python.exe app.py
```
Abre **http://127.0.0.1:5000**, pulsa **Crear cuenta** y registra tu empresa. Marca «Cargar 30 leads
de ejemplo» si quieres datos para probar. Para pararlo, pulsa `Ctrl + C`. Los datos quedan en PostgreSQL.

Si el puerto 5000 está ocupado (por ejemplo, por la versión antigua del CRM):
```powershell
.\.venv\Scripts\python.exe app.py --puerto 5050
```

### Si es un ordenador nuevo (instalación desde cero)
```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
```
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
```powershell
Copy-Item .env.example .env
```
Edita `.env` con el Bloc de notas (`notepad .env`) y rellena `DATABASE_URL` y `SECRET_KEY`.
Para generar la clave:
```powershell
-join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
```

## 2. Comprobar que todo funciona (pruebas automáticas)

Las pruebas usan una base aparte (`crm_test`) y no tocan tus datos.
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```
Debe terminar con `16 passed`.

## 3. Pasar los datos de la versión anterior (SQLite)

La versión anterior guardaba todo en `crm.db`. Primero cierra esa versión (`Ctrl + C` en su ventana)
y crea tu cuenta en la nueva. Después:
```powershell
.\.venv\Scripts\python.exe manage.py importar-sqlite crm.db TU_EMAIL
```
Copia los leads con su análisis, estado y notas a tu empresa. `crm.db` solo se lee, no se modifica.

## 4. Activar el panel de inteligencia artificial

1. Crea una clave en https://platform.claude.com (API keys). Este paso lo haces tú: la clave es privada.
2. Abre `.env` (`notepad .env`) y cambia la línea `# ANTHROPIC_API_KEY=...` por
   `ANTHROPIC_API_KEY=tu-clave` (sin `#` delante).
3. Reinicia el CRM.

Sin clave, el panel de IA dice que no está configurado y los leads siguen con el análisis del motor de
reglas. Cada llamada cuesta dinero en tu cuenta de la API. `LIMITE_IA_DIARIO` limita cuántas llamadas
hace cada empresa al día.

---

## 5. Publicarlo en Internet con Render

Render da la URL pública con **HTTPS automático**, una base **PostgreSQL gestionada** (los datos se
guardan aunque se reinicie la app) y despliega cada vez que subes cambios a GitHub.

### 5.1 Subir el proyecto a GitHub (una vez)

Instala Git:
```powershell
winget install --id Git.Git -e
```
Cierra y vuelve a abrir PowerShell para que reconozca `git`. Después:
```powershell
cd C:\Users\mario\CRM-Leads
```
```powershell
git init
```
```powershell
git add .
```
Comprueba que **no** aparecen `.env`, `.venv` ni `crm.db` (el `.gitignore` los excluye):
```powershell
git status
```
```powershell
git commit -m "CRM SaaS: Flask + PostgreSQL + autenticación multiempresa"
```
En https://github.com/new crea un repositorio **privado** llamado `crm-leads`, sin README. Luego
(cambia `TU_USUARIO`):
```powershell
git remote add origin https://github.com/TU_USUARIO/crm-leads.git
```
```powershell
git branch -M main
```
```powershell
git push -u origin main
```

### 5.2 Crear el servicio en Render

1. Entra en https://dashboard.render.com y conecta tu cuenta de GitHub.
2. Pulsa **New → Blueprint** y elige el repositorio `crm-leads`. Render lee `render.yaml` y propone:
   - **crm-db**: PostgreSQL gestionado.
   - **crm-leads**: el servicio web.
3. Te pedirá `ANTHROPIC_API_KEY`: pega tu clave o déjala vacía y añádela más tarde en
   *crm-leads → Environment*.
4. Pulsa **Apply**. El primer despliegue tarda unos minutos. Las tablas se crean solas al arrancar.
5. La URL pública aparece arriba en el servicio (`https://crm-leads-xxxx.onrender.com`). Ábrela y crea
   tu cuenta.

Las variables de entorno quedan así (ninguna está en el código):

| Variable | Valor en Render |
|---|---|
| `DATABASE_URL` | Automática, desde `crm-db` |
| `SECRET_KEY` | Generada por Render |
| `PRODUCCION` | `true`: cookies solo por HTTPS y cabecera HSTS |
| `ALLOW_SIGNUP` | `true` para registro abierto; `false` para cerrarlo |
| `ANTHROPIC_API_KEY` | Tu clave (opcional) |
| `LIMITE_IA_DIARIO` | `60` |

### 5.3 Publicar cambios
```powershell
git add .
```
```powershell
git commit -m "Describe el cambio"
```
```powershell
git push
```
Render vuelve a desplegar solo.

### 5.4 Planes y datos
- Los planes gratuitos de Render sirven para probar: el servicio web se duerme sin visitas (tarda
  unos segundos en despertar) y la base de datos gratuita caduca. **Para uso real pasa `crm-db` a un
  plan de pago**, que incluye copias de seguridad. Consulta los precios en render.com/pricing.
- Dominio propio con HTTPS: *crm-leads → Settings → Custom Domains*. Render crea el certificado.
- Copia manual de la base: *crm-db → Recovery/Backups* o, desde PowerShell, con `pg_dump` y la
  «External Database URL» de `crm-db`:
  ```powershell
  & 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe' --dbname "PEGA_AQUI_LA_EXTERNAL_DATABASE_URL" -Fc -f copia_crm.dump
  ```
- Los datos de ejemplo solo se cargan si alguien los pide al registrarse, y solo los ve esa empresa.
  No se publica nada sin iniciar sesión.

---

## Problemas frecuentes

| Mensaje | Solución |
|---|---|
| `Falta la variable DATABASE_URL` | No existe `.env` o le falta la línea. Mira `.env.example` |
| `connection refused` al arrancar | PostgreSQL está parado: `Start-Service postgresql-x64-17` (PowerShell como administrador) |
| El puerto está ocupado | `.\.venv\Scripts\python.exe app.py --puerto 5050` |
| «Demasiados intentos fallidos» | Espera 15 minutos: es la protección contra ataques |
| He olvidado mi contraseña | Pide a un administrador de tu empresa que te cree un acceso nuevo, o usa `manage.py crear-empresa` para empezar otra |
| El panel de IA dice «no configurada» | Falta `ANTHROPIC_API_KEY` en `.env` (local) o en *Environment* (Render). Reinicia después |
