"""
Datos de la empresa que usa el sistema.

Los textos de la capa 2 (correos, acciones) llevan los marcadores
{empresa}, {producto} y {firma}; la capa 3 los sustituye por estos valores.
Cámbialos aquí y vuelve a ejecutar capa3_salidas.py.
"""

EMPRESA = "Mi Empresa"
PRODUCTO = "nuestro CRM"
FIRMA = "Equipo comercial · Mi Empresa"

# Contexto que recibe la capa de IA para redactar con sentido
DESCRIPCION_NEGOCIO = (
    "Vendemos un CRM con automatización comercial para empresas de 20 a 1.000 empleados. "
    "Sectores objetivo: tecnología, retail, logística, salud e industria. "
    "Ticket medio entre 10.000 y 60.000 € al año. Implantación estándar de 4 a 6 semanas."
)


# Fecha "hoy" con la que la plataforma calcula los días sin contacto.
# Fija (AAAA-MM-DD) para que la demo dé siempre los mismos resultados;
# pon None para usar la fecha real de cada día.
FECHA_REFERENCIA = "2026-11-23"


def rellenar(texto: str) -> str:
    """Sustituye los marcadores en un texto."""
    return (str(texto).replace("{empresa}", EMPRESA)
            .replace("{producto}", PRODUCTO)
            .replace("{firma}", FIRMA))
