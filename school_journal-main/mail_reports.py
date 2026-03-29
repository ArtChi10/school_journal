# -*- coding: utf-8 -*-
import os
import time
import ssl
import smtplib
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional, Tuple

import gspread

# ====================== НАСТРОЙКИ ======================

# Где лежат отчёты (скрипт ищет во всех перечисленных корнях рекурсивно)
OUTPUT_ROOTS = [Path("pdf_out").resolve(), Path("output").resolve()]

# Google Sheet с контактами (твоя ссылка)
SPREADSHEET_URL = os.getenv("PARENT_REPORTS_SPREADSHEET_URL", "")
SHEET_GID = 0            # работаем по gid, чтобы не зависеть от имени листа
DATA_RANGE = "A1:D"      # A: индекс/пусто, B: ФИО, C: email1, D: email21

# Авторизация к Google Sheets:
# Вариант по умолчанию — через OAuth с client_secret.json (создаст token_gspread.json).
# Если используешь сервисный аккаунт — расшарь на него таблицу и укажи путь ниже.
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", "") or None

# Отправка через Яндекс (SMTP SSL)
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT_SSL = 465
YANDEX_LOGIN = os.getenv("SMTP_LOGIN", "")  # ← отправитель
YANDEX_APP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # ← пароль приложения
MAIL_FROM = os.getenv("SMTP_FROM", YANDEX_LOGIN)


# Тема и текст письма
MAIL_SUBJECT = "Отчёт по третьему модулю 2025–2026 — {student}"
MAIL_BODY = (
    "Дорогие родители!\n\n"
    "Высылаем вам отчёт за третий учебный модуль.\n\n"
    "Мы работаем над улучшением процесса создания обратной связи, поэтому рассылку отправляем вам несколько позже, чем планируется в дальнейшем.\n\n"
    "С уважением,\n"
    "ОЦ Школа Проектор"
)

# Пауза между письмами (сек), чтобы не триггерить лимиты SMTP
SEND_PAUSE = 2

# =======================================================
if not SPREADSHEET_URL:
    raise RuntimeError("Set PARENT_REPORTS_SPREADSHEET_URL in environment")

# ---------- доступ к Google Sheets ----------
def open_sheet():
    """
    Надёжно открывает таблицу по URL и возвращает worksheet по GID.
    Делает до 5 попыток на случай временных 500 ошибок API.
    """
    if SERVICE_ACCOUNT_JSON and os.path.exists(SERVICE_ACCOUNT_JSON):
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_JSON)
    else:
        gc = gspread.oauth(
            credentials_filename="client_secret.json",
            authorized_user_filename="token_gspread.json",
        )

    backoff = 1.0
    for attempt in range(5):
        try:
            sh = gc.open_by_url(SPREADSHEET_URL)
            ws = sh.get_worksheet_by_id(SHEET_GID)
            if ws is None:
                ws = sh.sheet1
            return ws
        except gspread.exceptions.APIError as e:
            msg = str(e)
            if ("Internal error" in msg or "500" in msg) and attempt < 4:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise


def read_contacts() -> List[Tuple[str, List[str]]]:
    """
    Возвращает список (student_name, [email1, email2]).
    ФИО из B, e-mail’ы из C и D (пустые игнорим).
    """
    ws = open_sheet()
    rows = ws.get(DATA_RANGE)  # список списков
    result = []
    for row in rows:
        fio = row[1].strip() if len(row) > 1 and row[1] else ""
        if not fio:
            continue
        emails = []
        if len(row) > 2 and row[2]:
            emails.append(row[2].strip())
        if len(row) > 3 and row[3]:
            emails.append(row[3].strip())
        result.append((fio, emails))
    return result


# ---------- поиск файла отчёта ----------
def normalize_name(s: str) -> str:
    return " ".join(s.lower().replace("_", " ").replace("-", " ").split())

def name_variants(fio: str) -> List[str]:
    """
    Возвращаем варианты для поиска по имени файла:
      'Имя Фамилия', 'Фамилия Имя' (в нижнем регистре, схлопнутые пробелы).
    """
    parts = [p for p in fio.split() if p]
    if len(parts) >= 2:
        first, last = parts[0], parts[1]
        return [normalize_name(f"{first} {last}"), normalize_name(f"{last} {first}")]
    return [normalize_name(fio)]

def is_student_in_filename(filename_stem: str, fio: str) -> bool:
    fn = normalize_name(filename_stem)
    for v in name_variants(fio):
        if v in fn:
            return True
    return False

def find_student_report_in_root(root: Path, fio: str) -> Optional[Path]:
    """
    Ищет файл в одном корне:
      1) сначала PDF,
      2) если нет — DOCX.
    Если несколько — берём самый свежий по mtime.
    """
    matches_pdf: List[Path] = []
    matches_docx: List[Path] = []
    if not root.exists():
        return None

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        stem = p.stem
        if ext == ".pdf" and is_student_in_filename(stem, fio):
            matches_pdf.append(p)
        elif ext == ".docx" and is_student_in_filename(stem, fio):
            matches_docx.append(p)

    pick_latest = lambda items: max(items, key=lambda x: x.stat().st_mtime) if items else None
    return pick_latest(matches_pdf) or pick_latest(matches_docx)

def find_student_report(roots: List[Path], fio: str) -> Optional[Path]:
    for r in roots:
        found = find_student_report_in_root(r, fio)
        if found:
            return found
    return None


# ---------- отправка через Яндекс SMTP ----------
def send_email_yandex(to_list: List[str], subject: str, body: str, attach_path: Path) -> bool:
    if not YANDEX_APP_PASSWORD or YANDEX_APP_PASSWORD.startswith("PASTE_"):
        print("✖ Не задан пароль приложения Яндекс (YANDEX_APP_PASSWORD).")
        return False

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(body)

    ctype, enc = mimetypes.guess_type(str(attach_path))
    if not ctype or enc:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    with open(attach_path, "rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=attach_path.name)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL, context=ctx, timeout=30) as smtp:
            smtp.login(YANDEX_LOGIN, YANDEX_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"✖ Ошибка SMTP-отправки '{attach_path.name}' → {to_list}: {e}")
        return False


# ---------- main ----------
def main():
    contacts = read_contacts()

    total = len(contacts)
    sent = 0
    missed = 0

    print(f"Найдено записей в таблице: {total}")
    for fio, emails in contacts:
        if not emails:
            print(f"- Пропуск (нет email): {fio}")
            missed += 1
            continue

        report = find_student_report(OUTPUT_ROOTS, fio)
        if not report:
            print(f"- Не найден файл для: {fio}")
            missed += 1
            continue

        subj = MAIL_SUBJECT.format(student=fio)
        ok = send_email_yandex(emails, subj, MAIL_BODY, report)
        if ok:
            try:
                # покажем относительный путь от подходящего корня
                shown = None
                for r in OUTPUT_ROOTS:
                    try:
                        shown = report.relative_to(r)
                        break
                    except Exception:
                        pass
                shown = shown or report
                print(f"✔ Отправлено {fio} → {', '.join(emails)} | {shown}")
            except Exception:
                print(f"✔ Отправлено {fio} → {', '.join(emails)} | {report}")
            sent += 1
            time.sleep(SEND_PAUSE)
        else:
            missed += 1

    print(f"\nИтог: отправлено {sent}, пропущено {missed} (из {total}).")


if __name__ == "__main__":
    main()
