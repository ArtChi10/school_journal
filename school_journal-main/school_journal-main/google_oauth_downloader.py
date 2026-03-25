# google_oauth_downloader.py
from __future__ import annotations
import io, os, re
from typing import Dict, List
from urllib.parse import urlparse

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

def _ensure_creds(client_secret_path: str = "client_secret.json", token_path: str = "token.json") -> Credentials:
    creds: Credentials | None = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                raise FileNotFoundError(
                    f"Не найден {client_secret_path}. Скачай OAuth client (Desktop app) в Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds

def _extract_spreadsheet_id(edit_url: str) -> str:
    u = urlparse(edit_url)
    parts = u.path.strip("/").split("/")
    try:
        i = parts.index("d")
        return parts[i+1]
    except Exception as exc:
        raise ValueError(f"Не удалось извлечь spreadsheetId из ссылки: {edit_url}") from exc

def _sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "untitled"

def download_sheet_as_xlsx_by_url(edit_url: str, out_path: str, client_secret_path: str = "client_secret.json") -> str:
    """
    Скачивает файл по ссылке редактирования:
      - Google Sheets -> export в .xlsx
      - обычный XLSX -> прямое скачивание
      - ярлык (shortcut) -> разворачиваем и повторяем логику
    """
    creds = _ensure_creds(client_secret_path)
    drive = build("drive", "v3", credentials=creds)
    file_id = _extract_spreadsheet_id(edit_url)

    # 1) узнаём тип файла (и разворачиваем ярлык)
    meta = drive.files().get(fileId=file_id, fields="id,name,mimeType,shortcutDetails").execute()
    if meta.get("mimeType") == "application/vnd.google-apps.shortcut":
        target_id = meta["shortcutDetails"]["targetId"]
        meta = drive.files().get(fileId=target_id, fields="id,name,mimeType").execute()
        file_id = meta["id"]

    mime = meta["mimeType"]
    name = meta.get("name") or "journal"

    # гарантируем .xlsx в имени
    base, ext = os.path.splitext(out_path)
    if ext.lower() != ".xlsx":
        out_path = base + ".xlsx"

    # 2) скачиваем по типу
    if mime == "application/vnd.google-apps.spreadsheet":
        # Google Sheets -> export
        request = drive.files().export(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        # уже XLSX -> прямая загрузка
        request = drive.files().get_media(fileId=file_id)
    else:
        raise RuntimeError(
            f"Файл с ID {file_id} имеет тип {mime}, который нельзя отдать как .xlsx. "
            "Это не Google-таблица и не XLSX."
        )

    # 3) сохраняем
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(fh.getvalue())
    return out_path



def download_class_journals_oauth(class_links: Dict[str, str], out_dir: str = "input/downloads") -> List[str]:
    """
    Для словаря {класс: ссылка} качает .xlsx как journal_{класс}.xlsx
    (имена очищаются от недопустимых символов).
    """
    saved: List[str] = []
    os.makedirs(out_dir, exist_ok=True)

    for cls, url in class_links.items():
        base = _sanitize_filename(cls)
        out_path = os.path.join(out_dir, f"journal_{base}.xlsx")
        p = download_sheet_as_xlsx_by_url(url, out_path)
        print(f"✔ {cls}: сохранён {p}")
        saved.append(p)

    print(f"Готово. Скачано файлов: {len(saved)} → {out_dir}")
    return saved
