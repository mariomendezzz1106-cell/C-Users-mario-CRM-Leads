"""Las pruebas usan la base crm_test (PostgreSQL real), nunca la de trabajo."""
import os
import re
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(RAIZ / ".env").get("DATABASE_URL", "")
if not url:
    pytest.exit("Falta DATABASE_URL en .env")
os.environ["DATABASE_URL"] = re.sub(r"/crm(\?|$)", r"/crm_test\1", url)
assert os.environ["DATABASE_URL"].rsplit("/", 1)[-1].startswith("crm_test"), "Las pruebas deben usar crm_test"
os.environ["ANTHROPIC_API_KEY"] = ""  # las pruebas no hacen llamadas de pago

from crm import create_app  # noqa: E402
from crm.modelos import Base, db  # noqa: E402


@pytest.fixture(scope="session")
def app():
    app = create_app({"TESTING": True})
    with app.app_context():
        Base.metadata.drop_all(db.engine)
        Base.metadata.create_all(db.engine)
    return app


@pytest.fixture(autouse=True)
def limpiar(app):
    yield
    with app.app_context():
        nombres = ", ".join(t.name for t in Base.metadata.sorted_tables)
        db.session.execute(db.text(f"TRUNCATE {nombres} RESTART IDENTITY CASCADE"))
        db.session.commit()


class Cliente:
    """Navegador de pruebas: guarda la cookie y añade las cabeceras que manda el panel."""

    def __init__(self, app):
        self.c = app.test_client()
        self.csrf = None

    def _csrf_form(self, ruta):
        html = self.c.get(ruta).get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', html).group(1)

    def registrar(self, empresa, email, clave="clave-segura-123", demo=False, nombre="Ana"):
        datos = {"csrf": self._csrf_form("/registro"), "empresa": empresa, "nombre": nombre, "email": email,
                 "clave": clave, "clave2": clave}
        if demo:
            datos["demo"] = "1"
        r = self.c.post("/registro", data=datos)
        self.cargar_csrf()
        return r

    def entrar(self, email, clave="clave-segura-123"):
        r = self.c.post("/login", data={"csrf": self._csrf_form("/login"), "email": email, "clave": clave})
        self.cargar_csrf()
        return r

    def cargar_csrf(self):
        r = self.c.get("/api/datos")
        self.csrf = r.get_json().get("csrf") if r.status_code == 200 else None

    def _h(self):
        return {"X-CRM": "1", "X-CSRF-Token": self.csrf or ""}

    def get(self, url, **k):
        return self.c.get(url, **k)

    def post(self, url, json=None, **k):
        return self.c.post(url, json=json, headers=self._h(), **k)

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers=self._h())

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self._h())

    def delete(self, url):
        return self.c.delete(url, headers=self._h())


@pytest.fixture
def nuevo(app):
    return lambda: Cliente(app)
