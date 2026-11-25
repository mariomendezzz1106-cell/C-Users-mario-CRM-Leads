"""
Reglas de negocio del lead scoring (CAPA 1).

Todo lo "ajustable" vive aquí para que el motor sea transparente y
explicable en clase: cambia un peso, vuelve a ejecutar y compara.
Puntuación máxima teórica = 100 (40 encaje + 35 intención + 25 engagement),
menos una penalización por falta de contacto reciente.
"""

# ── Umbrales de clasificación ─────────────────────────────────────────────
UMBRAL_HOT = 70
UMBRAL_WARM = 45

# Si un lead acumula este número de avisos (no críticos) también va a revisión
MAX_AVISOS = 3

# ── BLOQUE 1 · ENCAJE (máx. 40) ───────────────────────────────────────────
# (mínimo de empleados, puntos) — se evalúa de mayor a menor
TRAMOS_EMPLEADOS = [(500, 12), (200, 11), (100, 10), (50, 8), (20, 5), (10, 3), (1, 1)]

SECTORES_OBJETIVO = {"tecnologia", "retail", "logistica", "salud", "industria"}          # 10
SECTORES_SECUNDARIOS = {"energia", "servicios profesionales", "hosteleria",
                        "agroalimentario", "construccion"}                                # 6
PUNTOS_SECTOR = {"objetivo": 10, "secundario": 6, "otro": 2}

# Palabras clave (sin tildes, minúsculas) para detectar poder de decisión
CARGOS_DECISORES = ["ceo", "cto", "cfo", "coo", "director", "directora", "gerente",
                    "socio", "socia", "head of", "propietari", "fundador", "fundadora"]
CARGOS_INFLUENCIADORES = ["responsable", "jefe", "jefa", "coordinador", "coordinadora",
                          "manager", "lider", "tecnic"]
PUNTOS_CARGO = {"decisor": 12, "influenciador": 7, "otro": 2}

PUNTOS_PAIS = {"espana": 6, "portugal": 5, "mexico": 4, "colombia": 4,
               "chile": 4, "argentina": 4, "peru": 4}
PUNTOS_PAIS_OTRO = 2

# ── BLOQUE 2 · INTENCIÓN DE COMPRA (máx. 35) ──────────────────────────────
PUNTOS_PLAZO = {"inmediato": 15, "1-3 meses": 12, "3-6 meses": 7,
                "+6 meses": 3, "sin definir": 0}
TRAMOS_PRESUPUESTO = [(50000, 12), (25000, 10), (10000, 7), (5000, 4), (1, 1)]
PUNTOS_DEMO = 8

# ── BLOQUE 3 · ENGAGEMENT (máx. 25) ───────────────────────────────────────
TRAMOS_VISITAS = [(20, 8), (10, 6), (5, 4), (1, 2)]
TRAMOS_DESCARGAS = [(5, 6), (3, 4), (1, 2)]
TRAMOS_EMAILS = [(10, 5), (6, 4), (3, 2), (1, 1)]
PUNTOS_ORIGEN = {"referido": 6, "feria": 5, "webinar": 5, "web": 4,
                 "linkedin": 3, "email frio": 1}

# ── PENALIZACIÓN POR RECENCIA (días desde el último contacto) ─────────────
# (más de N días, penalización)
PENALIZACION_RECENCIA = [(180, -15), (90, -10), (30, -5)]

# ── VALIDACIÓN ────────────────────────────────────────────────────────────
CAMPOS_CRITICOS = ["email", "empresa", "empleados", "presupuesto_eur"]
DOMINIOS_GENERICOS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com",
                      "yahoo.es", "icloud.com", "live.com"}
# Presupuesto por empleado por encima del cual se considera sospechoso
MAX_PRESUPUESTO_POR_EMPLEADO = 5000
