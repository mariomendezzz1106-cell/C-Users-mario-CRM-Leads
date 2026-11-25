"""Punto de entrada para servidores de producción: gunicorn wsgi:app"""
from crm import create_app

app = create_app()
