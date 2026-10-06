"""Envío de correo por SMTP (sirve con Brevo, Amazon SES, Resend, Gmail con clave de aplicación...). Sin configurar, no hay avisos."""
from __future__ import annotations

import logging
import os
import re
import smtplib
import threading
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

log = logging.getLogger("stats42.mail")

# Una dirección razonable y sin nada que permita colar cabeceras o varios destinatarios.
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")


def valid_email(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 254 and bool(_EMAIL.fullmatch(value))


def mask_email(email: str) -> str:
    """a***@dominio: para enseñar al propio alumno qué dirección tenemos sin repetirla entera."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@dataclass(frozen=True)
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""          # p. ej. "42stats <avisos@tudominio.es>"
    reply_to: str = ""        # opcional: adonde llegan las respuestas (p. ej. tu@tudominio.es), distinto del remitente

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.sender)

    @classmethod
    def from_env(cls) -> "SmtpConfig":
        env = os.environ.get
        return cls(host=env("FT_SMTP_HOST", ""), port=int(env("FT_SMTP_PORT", "587")), user=env("FT_SMTP_USER", ""),
                   password=env("FT_SMTP_PASSWORD", ""), sender=env("FT_MAIL_FROM", ""), reply_to=env("FT_MAIL_REPLY_TO", ""))


class SmtpMailer:
    def __init__(self, cfg: SmtpConfig):
        self.cfg = cfg

    def send(self, to: str, subject: str, body: str) -> None:
        if not valid_email(to):
            raise ValueError("destinatario no válido")
        msg = EmailMessage()                              # rechaza saltos de línea en las cabeceras
        msg["From"], msg["To"], msg["Subject"] = self.cfg.sender, to, subject
        msg["Auto-Submitted"] = "auto-generated"          # que los autorrespondedores no contesten
        if valid_email(self.cfg.reply_to):
            msg["Reply-To"] = self.cfg.reply_to
        msg.set_content(body)
        with smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=15) as smtp:
            smtp.starttls()
            if self.cfg.user:
                smtp.login(self.cfg.user, self.cfg.password)
            smtp.send_message(msg)


def from_env() -> Mailer | None:
    cfg = SmtpConfig.from_env()
    return SmtpMailer(cfg) if cfg.enabled else None


def send_in_background(mailer: Mailer, to: str, subject: str, body: str) -> None:
    """Un fallo de correo nunca debe afectar a quien pulsó el botón: se registra el tipo de error y nada más (ni dirección ni texto)."""
    def run() -> None:
        try:
            mailer.send(to, subject, body)
        except Exception as exc:
            log.warning("no se pudo enviar un aviso (%s)", type(exc).__name__)
    threading.Thread(target=run, daemon=True).start()
