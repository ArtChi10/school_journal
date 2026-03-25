# -*- coding: utf-8 -*-
"""
DOCX на Google Drive -> PDF (без Word/LibreOffice):
1) скачать DOCX в память,
2) импортировать как временный Google Doc,
3) экспортировать PDF,
4) удалить временный Google Doc.

Запуск:
  python drive_docx_to_pdf_via_google.py --folder-id <ID_папки> --dst pdf_out
"""

import argparse
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaInMemoryUpload
from googleapiclient.errors import HttpError

# используем твой модуль OAuth (client_secret.json + token.json)
from google_oauth_downloader import _ensure_creds, SCOPES as DL_SCOPES  # type: ignore

MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_DOCX   = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_GDOC   = "application/vnd.google-apps.document"
MIME_PDF    = "application/pdf"

LIST_KW = dict(includeItemsFromAllDrives=True, supportsAllDrives=True)


def get_drive_service():
    # Нужен полный доступ, т.к. создаём/удаляем временные файлы
    DL_SCOPES[:] = ["https://www.googleapis.com/auth/drive"]
    creds = _ensure_creds()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def sanitize(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "untitled"


def list_children(service, folder_id: str) -> List[Dict]:
    q = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id,name,mimeType)"
    items, token = [], None
    while True:
        resp = service.files().list(q=q, fields=fields, pageToken=token, **LIST_KW).execute()
        items += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def download_docx_bytes(service, file_id: str) -> bytes:
    req = service.files().get_media(fileId=file_id)
    buf = BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def import_as_google_doc(service, docx_bytes: bytes, name: str, parent_id: Optional[str] = None) -> str:
    media = MediaInMemoryUpload(docx_bytes, mimetype=MIME_DOCX, resumable=False)
    meta = {"name": name, "mimeType": MIME_GDOC}
    if parent_id:
        meta["parents"] = [parent_id]
    created = service.files().create(
        body=meta, media_body=media, fields="id", supportsAllDrives=True
    ).execute()
    return created["id"]


def export_google_doc_to_pdf(service, gdoc_id: str) -> bytes:
    return service.files().export(fileId=gdoc_id, mimeType=MIME_PDF).execute()


def delete_file_quiet(service, file_id: str):
    try:
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
    except HttpError:
        pass


def walk_and_convert(service, folder_id: str, out_root: Path):
    """
    Рекурсивно обходит папку на Диске, повторяет структуру локально,
    конвертирует все DOCX в PDF.
    """
    stack: List[Dict] = [{"id": folder_id, "out_dir": out_root}]
    converted = skipped = errors = 0

    while stack:
        node = stack.pop()
        local_dir: Path = node["out_dir"]
        local_dir.mkdir(parents=True, exist_ok=True)

        try:
            children = list_children(service, node["id"])
        except HttpError as e:
            print(f"✖ Не удалось прочитать папку {node['id']}: {e}")
            errors += 1
            continue

        for item in children:
            fid = item["id"]
            name = sanitize(item["name"])
            mime = item.get("mimeType", "")

            if mime == MIME_FOLDER:
                # заходим в подпапку и отражаем её локально
                stack.append({"id": fid, "out_dir": local_dir / name})
                continue

            if mime != MIME_DOCX:
                skipped += 1
                continue

            try:
                # логи без .docx
                print(f"→ {name}")
                docx_bytes = download_docx_bytes(service, fid)

                # временный Google Doc создаём без родителя
                temp_id = import_as_google_doc(service, docx_bytes, name=f"__tmp__{name}", parent_id=None)

                pdf_bytes = export_google_doc_to_pdf(service, temp_id)
                out_path = (local_dir / name).with_suffix(".pdf")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(pdf_bytes)

                print(f"   ✔ {out_path}")
                converted += 1
            except Exception as e:
                print(f"   ✖ Ошибка: {e}")
                errors += 1
            finally:
                if 'temp_id' in locals():
                    delete_file_quiet(service, temp_id)

    print(f"\nИтог: PDF сконвертировано {converted}, пропущено (не DOCX) {skipped}, ошибок {errors}.")


def main():
    ap = argparse.ArgumentParser(description="DOCX из папки Google Drive -> PDF (через временный Google Doc).")
    ap.add_argument("--folder-id", required=True, help="ID папки на Диске")
    ap.add_argument("--dst", required=True, help="Локальная папка для сохранения PDF")
    args = ap.parse_args()

    out_root = Path(args.dst).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    svc = get_drive_service()
    walk_and_convert(svc, args.folder_id, out_root)


if __name__ == "__main__":
    main()
