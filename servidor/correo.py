"""Envio del enlace magico por correo.

Configuracion por entorno (se lee en CADA envio, no al importar):
  SMTP_HOST   servidor SMTP. Sin el -> modo desarrollo: el enlace se escribe
              en el log (logger "servidor.correo", nivel WARNING para que se
              vea aunque nadie configure logging) y se devuelve "dev".
  SMTP_PORT   puerto (defecto 587). 587 -> STARTTLS; 465 -> SMTP sobre TLS.
  SMTP_USER   usuario para login (opcional; sin el no se autentica).
  SMTP_PASS   clave del usuario SMTP.
  SMTP_FROM   remitente (defecto SMTP_USER o "no-responder@pergamundi.com").
  BASE_URL    origen publico para componer la URL del enlace
              (defecto http://127.0.0.1:8000, sin barra final).
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("servidor.correo")

BASE_URL_DEFECTO = "http://127.0.0.1:8000"


def base_url(request=None):
    """Origen publico del sitio (sin barra final). BASE_URL del entorno manda;
    sin ella, el origen de la peticion si se pasa (OG, enlaces absolutos), y en
    ultimo termino el valor por defecto de desarrollo."""
    env = os.environ.get("BASE_URL")
    if env:
        return env.rstrip("/")
    if request is not None:
        try:
            return str(request.base_url).rstrip("/")
        except Exception:
            pass
    return BASE_URL_DEFECTO.rstrip("/")


def url_entrar(token):
    """URL absoluta del enlace magico para un token."""
    return "%s/entrar/%s" % (base_url(), token)


def _mensaje(email, url, remitente):
    msg = EmailMessage()
    msg["Subject"] = "Tu enlace para entrar en Pergamundi"
    msg["From"] = remitente
    msg["To"] = email
    msg.set_content(
        "Hola:\n\n"
        "Pulsa este enlace para entrar en Pergamundi:\n\n"
        "%s\n\n"
        "Caduca en 15 minutos y solo sirve una vez. Si no lo pediste, "
        "ignora este correo.\n" % url)
    return msg


def enviar_enlace(email, url):
    """Envia el enlace magico a `email`. Devuelve "smtp" o "dev".

    Lanza la excepcion de smtplib/socket si el envio SMTP falla (el llamador
    decide la respuesta HTTP)."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.warning("enlace magico (modo dev) para %s: %s", email, url)
        return "dev"
    puerto = int(os.environ.get("SMTP_PORT") or 587)
    usuario = os.environ.get("SMTP_USER") or ""
    clave = os.environ.get("SMTP_PASS") or ""
    remitente = (os.environ.get("SMTP_FROM") or usuario
                 or "no-responder@pergamundi.com")
    msg = _mensaje(email, url, remitente)
    ctx = ssl.create_default_context()
    if puerto == 465:
        smtp = smtplib.SMTP_SSL(host, puerto, timeout=15, context=ctx)
    else:
        smtp = smtplib.SMTP(host, puerto, timeout=15)
    with smtp:
        if puerto == 587:
            smtp.starttls(context=ctx)
        if usuario:
            smtp.login(usuario, clave)
        smtp.send_message(msg)
    log.info("enlace magico enviado por SMTP a %s", email)
    return "smtp"
