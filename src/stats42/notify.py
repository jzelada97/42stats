"""Avisos por correo, siempre opt-in. Plantillas fijas: nunca llevan texto escrito por otros alumnos, solo un login (validado), el nombre de
un proyecto y enlaces de esta web. Tope diario por destinatario para que esto no sirva de altavoz ni de spam."""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import helpboard
from . import mailer as mailmod
from .db import MailPref

log = logging.getLogger("stats42.mail")
DAILY_CAP = 6
_LOGIN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$", re.I)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

FOOT = "\n—\nRecibes este correo porque activaste los avisos en {base}/ayuda. Puedes desactivarlos cuando quieras en {base}/ayuda#avisos.\n"


def _clean(text: str) -> str:
    return _CTRL.sub(" ", str(text))[:120]


def _today() -> date:
    return datetime.now(timezone.utc).date()


class Notifier:
    def __init__(self, settings_db, main_engine, mailer: mailmod.Mailer | None, base_url: str, *, sync: bool = False):
        self.settings_db, self.main_engine, self.mailer, self.base, self.sync = settings_db, main_engine, mailer, base_url.rstrip("/"), sync

    @property
    def enabled(self) -> bool:
        return self.mailer is not None

    # ---------------------------------------------------------------- preferencias
    def available(self) -> bool:
        return self.enabled

    def save_email(self, uid: int, email: str) -> bool:
        """Guarda la dirección del propio alumno (solo tras activar los avisos él mismo y pasar por 42)."""
        if not self.enabled or not mailmod.valid_email(email):
            return False
        with Session(self.settings_db()) as db:
            row = db.get(MailPref, uid) or MailPref(user_id=uid, created_at=datetime.now(timezone.utc), sent_count=0)
            row.email = email
            db.add(row)
            db.commit()
        return True

    def get(self, uid: int) -> MailPref | None:
        with Session(self.settings_db()) as db:
            return db.get(MailPref, uid)

    def disable(self, uid: int) -> None:
        with Session(self.settings_db()) as db:
            db.query(MailPref).filter(MailPref.user_id == uid).delete()
            db.commit()

    # ---------------------------------------------------------------- envío
    def _deliver(self, db: Session, pref: MailPref, subject: str, body: str) -> bool:
        """Respeta el tope diario y entrega (en segundo plano en la web; en el acto en la tarea diaria y en los tests)."""
        today = _today()
        if pref.sent_day != today:
            pref.sent_day, pref.sent_count = today, 0
        if (pref.sent_count or 0) >= DAILY_CAP:
            return False
        pref.sent_count = (pref.sent_count or 0) + 1
        db.commit()
        text = body + FOOT.format(base=self.base)
        if self.sync:
            try:
                self.mailer.send(pref.email, subject, text)
            except Exception as exc:
                log.warning("no se pudo enviar un aviso (%s)", type(exc).__name__)
                return False
        else:
            mailmod.send_in_background(self.mailer, pref.email, subject, text)
        return True

    def _to(self, uid: int, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        try:
            with Session(self.settings_db()) as db:
                pref = db.get(MailPref, uid)
                return pref is not None and self._deliver(db, pref, subject, body)
        except Exception as exc:        # un aviso nunca puede romper la acción del alumno
            log.warning("fallo preparando un aviso (%s)", type(exc).__name__)
            return False

    # ---------------------------------------------------------------- avisos
    def offered_help(self, asker_uid: int, mentor_login: str, project: str) -> bool:
        if not _LOGIN.match(mentor_login or ""):
            return False
        return self._to(asker_uid, f"{mentor_login} quiere ayudarte con {_clean(project)}", (
            f"Hola,\n\n{mentor_login} se ha ofrecido a ayudarte con «{_clean(project)}» en la ayuda entre alumnos de 42 Madrid.\n\n"
            f"Escríbele por su perfil de 42: https://profile.intra.42.fr/users/{mentor_login}\n\n"
            f"Cuando te haya ayudado, cierra tu petición y agradécele aquí: {self.base}/ayuda#pedir\n\n"
            "Recuerda: se ayuda explicando, nunca pasando código."))

    def thanks_to_confirm(self, mentor_uid: int, project: str) -> bool:
        return self._to(mentor_uid, "Te han agradecido una ayuda: confírmala", (
            f"Hola,\n\nAlguien te ha agradecido tu ayuda con «{_clean(project)}». Para que cuente como punto, confirma que explicaste el tema "
            f"sin dar código (o niégalo si no fuiste tú): {self.base}/ayuda#peticiones\n"))

    def digest(self, cursus_id: int = 21) -> int:
        """Resumen diario a los mentores con peticiones sin responder en sus proyectos. Devuelve cuántos correos salieron."""
        if not self.enabled:
            return 0
        sent, today = 0, _today()
        with Session(self.settings_db()) as db, Session(self.main_engine) as ms:
            prefs = db.execute(select(MailPref)).scalars().all()
            for pref in prefs:
                if pref.last_digest == today:
                    continue
                waiting = [r for r in helpboard.incoming_requests(db, ms, pref.user_id, cursus_id) if not r["offered"]]
                if not waiting:
                    continue
                lines = "\n".join(f"- {_clean(name)}: {n}" for name, n in sorted(Counter(r["project"] for r in waiting).items()))
                if self._deliver(db, pref, "Hay alumnos pidiendo ayuda en tus proyectos",
                                 f"Hola,\n\nPeticiones abiertas en los proyectos en los que eres mentor y a las que aún no te has ofrecido:\n\n{lines}\n\n"
                                 f"Si puedes echar una mano: {self.base}/ayuda#peticiones\n"):
                    pref.last_digest = today
                    db.commit()
                    sent += 1
        return sent
