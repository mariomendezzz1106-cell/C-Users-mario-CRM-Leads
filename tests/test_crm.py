"""Pruebas de cada funcionalidad contra PostgreSQL."""
from crm.modelos import Usuario, db


# ── autenticación y sesiones ──────────────────────────────────────────────
def test_registro_crea_empresa_y_hash_argon2(app, nuevo):
    c = nuevo()
    r = c.registrar("Acme", "ana@acme.test")
    assert r.status_code == 302
    with app.app_context():
        u = db.session.execute(db.select(Usuario)).scalar_one()
        assert u.rol == "propietario" and u.hash.startswith("$argon2id$") and "clave-segura-123" not in u.hash
    d = c.get("/api/datos").get_json()
    assert d["meta"]["empresa"] == "Acme" and d["leads"] == []


def test_registro_valida(nuevo):
    c = nuevo()
    assert c.registrar("Acme", "no-es-email").status_code == 400
    assert c.registrar("Acme", "a@acme.test", clave="corta").status_code == 400
    c.registrar("Acme", "a@acme.test")
    assert nuevo().registrar("Otra", "a@acme.test").status_code == 400  # email repetido


def test_login_logout_y_persistencia(nuevo):
    c = nuevo()
    c.registrar("Acme", "ana@acme.test", demo=True)
    assert len(c.get("/api/datos").get_json()["leads"]) == 30
    c.post("/api/clientes", {"nombre": "Cliente persistente"})
    c.c.post("/logout", data={"csrf": c.csrf})
    assert c.get("/api/datos").status_code == 401
    assert c.get("/").status_code == 302
    assert nuevo().entrar("ana@acme.test", "mal-clave-xxx").status_code == 401
    c2 = nuevo()
    assert c2.entrar("ana@acme.test").status_code == 302
    assert len(c2.get("/api/datos").get_json()["leads"]) == 30
    assert c2.get("/api/clientes").get_json()[0]["nombre"] == "Cliente persistente"


def test_limite_de_intentos(nuevo):
    nuevo().registrar("Acme", "ana@acme.test")
    c = nuevo()
    for _ in range(5):
        assert c.entrar("ana@acme.test", "incorrecta-123").status_code == 401
    assert c.entrar("ana@acme.test").status_code == 429  # bloqueado aunque la clave sea buena


def test_csrf_obligatorio(nuevo):
    c = nuevo()
    c.registrar("Acme", "ana@acme.test")
    assert c.c.post("/api/clientes", json={"nombre": "X"}, headers={"X-CRM": "1"}).status_code == 403
    assert c.c.post("/api/clientes", json={"nombre": "X"}, headers={"X-CRM": "1", "X-CSRF-Token": "falso"}).status_code == 403
    assert c.post("/api/clientes", {"nombre": "X"}).status_code == 201


def test_cambio_clave_cierra_otras_sesiones(nuevo):
    a = nuevo(); a.registrar("Acme", "ana@acme.test")
    b = nuevo(); b.entrar("ana@acme.test")
    r = a.post("/api/cuenta/clave", {"actual": "clave-segura-123", "nueva": "otra-clave-456"})
    a.csrf = r.get_json()["csrf"]
    assert a.get("/api/datos").status_code == 200
    assert b.get("/api/datos").status_code == 401
    assert nuevo().entrar("ana@acme.test", "otra-clave-456").status_code == 302


# ── separación de empresas ────────────────────────────────────────────────
def test_aislamiento_entre_empresas(nuevo):
    a = nuevo(); a.registrar("Acme", "ana@acme.test", demo=True)
    b = nuevo(); b.registrar("Beta", "bea@beta.test")
    cid = a.post("/api/clientes", {"nombre": "Secreto SA"}).get_json()["id"]
    oid = a.post("/api/oportunidades", {"titulo": "Trato", "importe": 1000}).get_json()["id"]
    tid = a.post("/api/tareas", {"titulo": "Llamar"}).get_json()["id"]
    assert b.get("/api/datos").get_json()["leads"] == []
    assert b.get("/api/clientes").get_json() == []
    assert b.get(f"/api/clientes/{cid}").status_code == 404
    assert b.put(f"/api/clientes/{cid}", {"nombre": "Hackeado"}).status_code == 404
    assert b.delete(f"/api/oportunidades/{oid}").status_code == 404
    assert b.patch(f"/api/tareas/{tid}/estado", {"estado": "Hecha"}).status_code == 404
    assert b.get("/api/leads/L001/historial").status_code == 404
    assert b.delete("/api/leads/L001").status_code == 404
    # no se puede enlazar un registro propio con un cliente de otra empresa
    assert b.post("/api/contactos", {"nombre": "Eva", "cliente_id": cid}).status_code == 400
    assert a.get(f"/api/clientes/{cid}").get_json()["nombre"] == "Secreto SA"


# ── permisos por usuario ──────────────────────────────────────────────────
def test_roles(nuevo):
    a = nuevo(); a.registrar("Acme", "ana@acme.test")
    assert a.post("/api/usuarios", {"nombre": "Luis", "email": "luis@acme.test", "clave": "clave-lectura-1", "rol": "lectura"}).status_code == 201
    assert a.post("/api/usuarios", {"nombre": "Cris", "email": "cris@acme.test", "clave": "clave-comercial-1", "rol": "comercial"}).status_code == 201
    lect = nuevo(); lect.entrar("luis@acme.test", "clave-lectura-1")
    assert lect.get("/api/clientes").status_code == 200
    assert lect.post("/api/clientes", {"nombre": "X"}).status_code == 403
    com = nuevo(); com.entrar("cris@acme.test", "clave-comercial-1")
    assert com.post("/api/clientes", {"nombre": "X"}).status_code == 201
    assert com.get("/api/usuarios").status_code == 403
    # quitar el acceso cierra su sesión al momento
    uid = [u for u in a.get("/api/usuarios").get_json() if u["email"] == "cris@acme.test"][0]["id"]
    a.patch(f"/api/usuarios/{uid}", {"activo": False})
    assert com.get("/api/clientes").status_code == 401
    assert nuevo().entrar("cris@acme.test", "clave-comercial-1").status_code == 401
    yo = a.get("/api/datos").get_json()["usuario"]["id"]
    assert a.delete(f"/api/usuarios/{yo}").status_code == 400


# ── leads: clasificación, búsqueda, seguimiento, conversión ───────────────
def test_leads_motor_y_filtros(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test", demo=True)
    d = c.get("/api/datos").get_json()
    assert d["estadisticas"]["por_clase"]["HOT"]["n"] == 8 and d["estadisticas"]["por_clase"]["REVISAR DATOS"]["n"] == 6
    assert len(c.get("/api/leads?clase=HOT").get_json()) == 8
    assert [l["id_lead"] for l in c.get("/api/leads?q=softwave").get_json()] in (["L005", "L029"], ["L029", "L005"])
    r = c.post("/api/leads", {"empresa": "Nueva SL", "email": "x@nueva.test", "telefono": "+34 600 000 000",
                              "cargo": "CEO", "sector": "Tecnología", "empleados": "300", "pais": "España",
                              "presupuesto_eur": "50000", "plazo_compra": "Inmediato", "demo_solicitada": "Sí",
                              "visitas_web": "20", "fecha_alta": "2026-11-01", "ultimo_contacto": "2026-11-20"})
    assert r.status_code == 201 and r.get_json()["id_lead"] == "L031" and r.get_json()["clasificacion"] == "HOT"
    r = c.put("/api/leads/L031", {"empresa": "Nueva SL", "email": "mal@@x", "presupuesto_eur": "50000"})
    assert r.get_json()["clasificacion"] == "REVISAR DATOS"
    assert c.post("/api/leads", {"empresa": ""}).status_code == 400
    assert c.patch("/api/leads/L001/seguimiento", {"estado": "En curso", "notas": "Llamada hecha"}).status_code == 200
    assert c.patch("/api/leads/L001/seguimiento", {"estado": "Inventado"}).status_code == 400
    h = c.get("/api/leads/L001/historial").get_json()
    assert h[0]["accion"] == "Seguimiento"
    r = c.post("/api/leads/L001/convertir")
    assert r.status_code == 201 and r.get_json()["oportunidad"]["importe"] == 45000
    assert c.post("/api/leads/L001/convertir").status_code == 400
    cli = c.get("/api/clientes?q=iberia").get_json()
    assert cli[0]["contactos"] == 1 and cli[0]["oportunidades_abiertas"] == 1
    assert c.delete("/api/leads/L031").status_code == 200
    assert c.get("/api/leads/L031/historial").status_code == 404


def test_importar_csv(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test")
    with open("datos/leads.csv", "rb") as f:
        r = c.post("/api/importar", data={"fichero": (f, "leads.csv")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["importados"] == 30
    from io import BytesIO
    r = c.post("/api/importar", data={"fichero": (BytesIO(b"a,b\n1,2"), "x.txt")}, content_type="multipart/form-data")
    assert r.status_code == 400


# ── clientes, contactos, oportunidades, tareas ────────────────────────────
def test_crud_clientes_y_contactos(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test")
    assert c.post("/api/clientes", {"nombre": ""}).status_code == 400
    r = c.post("/api/clientes", {"nombre": "Alfa", "empleados": "-3"})
    assert r.status_code == 400 and "empleados" in r.get_json()["errores"]
    cid = c.post("/api/clientes", {"nombre": "Alfa", "sector": "Retail", "empleados": "50", "ciudad": "Madrid"}).get_json()["id"]
    c.post("/api/clientes", {"nombre": "Beta", "sector": "Salud"})
    assert [x["nombre"] for x in c.get("/api/clientes?sector=Retail").get_json()] == ["Alfa"]
    assert [x["nombre"] for x in c.get("/api/clientes?q=madr").get_json()] == ["Alfa"]
    assert c.put(f"/api/clientes/{cid}", {"nombre": "Alfa Group", "tipo": "Cliente"}).get_json()["tipo"] == "Cliente"
    assert c.post("/api/contactos", {"nombre": "Eva", "email": "mal"}).status_code == 400
    kid = c.post("/api/contactos", {"nombre": "Eva", "email": "EVA@alfa.test", "cliente_id": cid}).get_json()["id"]
    assert c.get(f"/api/contactos?cliente_id={cid}").get_json()[0]["email"] == "eva@alfa.test"
    assert c.get(f"/api/clientes/{cid}").get_json()["contactos_lista"][0]["id"] == kid
    assert c.put(f"/api/contactos/{kid}", {"nombre": "Eva", "cargo": "CTO", "cliente_id": cid}).get_json()["cargo"] == "CTO"
    assert c.delete(f"/api/contactos/{kid}").status_code == 200
    assert c.delete(f"/api/clientes/{cid}").status_code == 200
    assert c.get(f"/api/clientes/{cid}").status_code == 404


def test_oportunidades_embudo_y_tareas(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test")
    cid = c.post("/api/clientes", {"nombre": "Alfa"}).get_json()["id"]
    assert c.post("/api/oportunidades", {"titulo": "X", "importe": "-5"}).status_code == 400
    assert c.post("/api/oportunidades", {"titulo": "X", "etapa": "Rara"}).status_code == 400
    o = c.post("/api/oportunidades", {"titulo": "Licencias", "importe": "20000", "cliente_id": cid, "etapa": "Propuesta"}).get_json()
    assert o["probabilidad"] == 50 and o["ponderado"] == 10000
    c.post("/api/oportunidades", {"titulo": "Otra", "importe": "5000"})
    assert len(c.get("/api/oportunidades?etapa=Propuesta").get_json()) == 1
    assert len(c.get("/api/oportunidades?q=alfa").get_json()) == 1
    r = c.patch(f"/api/oportunidades/{o['id']}/etapa", {"etapa": "Ganado"}).get_json()
    assert r["probabilidad"] == 100 and r["fecha_cierre"]
    assert c.get(f"/api/clientes/{cid}").get_json()["tipo"] == "Cliente"
    t = c.post("/api/tareas", {"titulo": "Enviar contrato", "vence": "2020-01-01", "oportunidad_id": o["id"], "cliente_id": cid}).get_json()
    assert t["vencida"] and t["asignado"] == "Ana"
    assert c.post("/api/tareas", {"titulo": "X", "vence": "31/12/2026"}).status_code == 400
    assert len(c.get("/api/tareas?vencidas=1").get_json()) == 1
    assert c.patch(f"/api/tareas/{t['id']}/estado", {"estado": "Hecha"}).get_json()["completada"]
    assert c.get("/api/tareas?vencidas=1").get_json() == []
    d = c.get("/api/dashboard").get_json()
    assert d["oportunidades"]["ganadas"] == 1 and d["oportunidades"]["abiertas"] == 1 and d["oportunidades"]["tasa_cierre"] == 100.0
    assert c.delete(f"/api/oportunidades/{o['id']}").status_code == 200
    assert c.delete(f"/api/tareas/{t['id']}").status_code == 200


# ── informes y descargas ──────────────────────────────────────────────────
def test_informes_y_descargas(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test", demo=True)
    c.post("/api/oportunidades", {"titulo": "Licencias", "importe": "1000"})
    inf = c.get("/api/informes").get_json()
    assert inf["leads_por_clase"]["HOT"]["n"] == 8 and inf["por_responsable"][0]["abiertas"] == 1
    for tipo, firma in [("excel", b"PK"), ("informe", "# Informe".encode()), ("hubspot", "﻿First Name".encode()),
                        ("oportunidades", "﻿ID;".encode()), ("clientes", "﻿ID;".encode())]:
        r = c.get(f"/descargas/{tipo}")
        assert r.status_code == 200 and r.data.startswith(firma), tipo
    assert c.get("/descargas/otra").status_code == 404
    otro = nuevo()
    assert otro.get("/descargas/excel").status_code == 401


# ── ajustes y panel de IA ─────────────────────────────────────────────────
def test_ajustes_y_ia_sin_clave(nuevo):
    c = nuevo(); c.registrar("Acme", "ana@acme.test", demo=True)
    assert c.put("/api/organizacion", {"nombre": "Acme Corp", "producto": "AcmeCRM", "firma": "Equipo Acme"}).status_code == 200
    l = [x for x in c.get("/api/datos").get_json()["leads"] if x["id_lead"] == "L001"][0]
    assert "Equipo Acme" in l["analisis"]["correo"]["cuerpo"] or "{firma}" not in l["analisis"]["correo"]["cuerpo"]
    assert c.post("/api/organizacion/demo").status_code == 400  # ya tiene leads
    assert c.get("/api/ia/estado").get_json()["configurada"] is False
    r = c.post("/api/leads/L001/convertir")  # noqa: F841
    for url, body in [("/api/ia/leads/L002/analizar", None), ("/api/ia/resumen", None), ("/api/ia/preguntar", {"pregunta": "¿Qué hago hoy?"})]:
        r = c.post(url, body)
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.get_json()["error"]


def test_importar_desde_sqlite(app, nuevo, tmp_path):
    import json, sqlite3
    import manage
    ruta = tmp_path / "viejo.db"
    con = sqlite3.connect(ruta)
    con.executescript("CREATE TABLE leads (id_lead TEXT, datos TEXT, resultado TEXT, analisis TEXT, estado TEXT, notas TEXT);"
                      "CREATE TABLE ajustes (clave TEXT, valor TEXT);")
    con.execute("INSERT INTO leads VALUES (?,?,?,?,?,?)", ("L007", json.dumps({"empresa": "Vieja SA", "email": "a@vieja.test"}),
                "{}", json.dumps({"accion": "Llamar", "prioridad": "P1"}), "En curso", "nota antigua"))
    con.commit(); con.close()
    c = nuevo(); c.registrar("Acme", "ana@acme.test")
    with app.app_context():
        manage.importar_sqlite(str(ruta), "ana@acme.test")
    l = c.get("/api/datos").get_json()["leads"][0]
    assert l["id_lead"] == "L007" and l["estado"] == "En curso" and l["analisis"]["accion"] == "Llamar"
    assert c.post("/api/leads", {"empresa": "Siguiente"}).get_json()["id_lead"] == "L008"


def test_cabeceras_y_salud(nuevo):
    c = nuevo()
    r = c.get("/salud")
    assert r.status_code == 200 and r.get_json()["estado"] == "ok"
    r = c.get("/login")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"
    assert "HttpOnly" in c.c.post("/login", data={}).headers.get("Set-Cookie", "HttpOnly")
