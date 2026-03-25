# drive_uploader.py
# -*- coding: utf-8 -*-
"""
Загрузка готовых отчётов на Google Диск с сохранением структуры:
  <ROOT>/<CLASS>/<файлы.docx>

Использует те же OAuth-учётки, что и твой google_oauth_downloader.py
(client_secret.json + token.json).
"""

import os
import argparse
from typing import Optional, Dict, List

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ---- НАСТРОЙКИ ПО УМОЛЧАНИЮ ----
DEFAULT_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
DEFAULT_DRIVE_ROOT = "1EWQ3fTwkvlbfgzq-vOSt_U7kLA1ddJfS"
# ---------------------------------


def get_drive_service():
    """
    1) Насильно включаем полный скоуп Drive у твоего oauth-модуля.
    2) Если token.json создан со старыми скоупами — удаляем, чтобы пройти re-consent.
    3) Строим сервис с поддержкой Shared Drives.
    """
    from google_oauth_downloader import _ensure_creds, SCOPES as DL_SCOPES  # type: ignore

    # (А) Полный доступ – чтобы создавать/удалять где угодно
    desired_scopes = ["https://www.googleapis.com/auth/drive"]
    DL_SCOPES[:] = desired_scopes

    # (Б) Сносим старый токен, если он с другими скоупами
    token_paths = []
    try:
        from google_oauth_downloader import TOKEN_PATH as DL_TOKEN_PATH  # type: ignore
        token_paths.append(DL_TOKEN_PATH)
    except Exception:
        pass
    # частые места, где лежит token.json
    token_paths += [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.json"),
        "token.json",
    ]
    for p in token_paths:
        try:
            if os.path.exists(p):
                # не удаляем слепо: попробуем определить, что скоупы не совпадают
                # если не можем – лучше удалить, чтобы точно получить re-consent
                os.remove(p)
                break
        except Exception:
            pass

    creds = _ensure_creds()  # без параметров (у твоей функции нет аргументов)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_single_by_name(service, name: str, parent_id: Optional[str],
                         mime: Optional[str] = None) -> Optional[Dict]:
    # экранируем одинарные кавычки
    safe = name.replace("'", "\\'")
    q_parts = [f"name = '{safe}'", "trashed = false"]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    if mime:
        q_parts.append(f"mimeType = '{mime}'")
    q = " and ".join(q_parts)
    res = service.files().list(
        q=q, spaces="drive",
        fields="files(id,name,mimeType,parents)",
        includeItemsFromAllDrives=True, supportsAllDrives=True
    ).execute()
    items = res.get("files", [])
    return items[0] if items else None


def ensure_folder(service, name: str, parent_id: Optional[str]) -> str:
    folder_mime = "application/vnd.google-apps.folder"
    found = _find_single_by_name(service, name, parent_id, mime=folder_mime)
    if found:
        return found["id"]
    meta = {"name": name, "mimeType": folder_mime}
    if parent_id:
        meta["parents"] = [parent_id]
    created = service.files().create(
        body=meta, fields="id", supportsAllDrives=True
    ).execute()
    return created["id"]


def delete_if_exists(service, name: str, parent_id: str):
    existing = _find_single_by_name(service, name, parent_id)
    if existing:
        service.files().delete(fileId=existing["id"], supportsAllDrives=True).execute()


def upload_file(service, local_path: str, parent_id: str):
    """Загрузка с перезаписью по имени в указанной папке."""
    fname = os.path.basename(local_path)

    # перезаписываем по имени: удалим старый, если есть
    delete_if_exists(service, fname, parent_id)

    mime = None
    if fname.lower().endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    meta = {"name": fname, "parents": [parent_id]}
    file = service.files().create(
        body=meta, media_body=media,
        fields="id,name,parents",
        supportsAllDrives=True
    ).execute()
    return file["id"]


def walk_class_folders(src_root: str) -> List[Dict]:
    """
    Собирает подпапки-классы и файлы в них.
    Возвращает [{"class": "<имя папки>", "files": [пути]}]
    """
    result: List[Dict] = []
    if not os.path.isdir(src_root):
        return result

    for entry in sorted(os.listdir(src_root)):
        class_dir = os.path.join(src_root, entry)
        if not os.path.isdir(class_dir):
            continue
        if entry.lower() == "temp":
            continue

        files = []
        for f in sorted(os.listdir(class_dir)):
            p = os.path.join(class_dir, f)
            if os.path.isfile(p):
                files.append(p)
        if files:
            result.append({"class": entry, "files": files})

    return result


def run_upload(src_root: str,
               drive_root_name: str,
               parent_id: Optional[str] = None,
               only_docx: bool = True,
               root_id: Optional[str] = None):
    """
    Если root_id задан — используем эту папку как корневую.
    Иначе создаём/находим корневую по имени (внутри parent_id, если задан).
    Внутри корневой создаём папки по классам и загружаем файлы.
    """
    service = get_drive_service()

    if root_id:
        print(f"[GDRIVE] Использую существующую папку как корневую: {root_id}")
        final_root_id = root_id
    else:
        print(f"[GDRIVE] Корневая папка: {drive_root_name}")
        final_root_id = ensure_folder(service, drive_root_name, parent_id=parent_id)

    classes = walk_class_folders(src_root)
    print(f"[LOCAL] Папок классов: {len(classes)} в {src_root}")

    for item in classes:
        cls = item["class"]
        files = item["files"]
        if only_docx:
            files = [p for p in files if p.lower().endswith(".docx")]
        print(f"\n[UPLOAD] Класс: {cls}  файлов: {len(files)}")

        class_folder_id = ensure_folder(service, cls, parent_id=final_root_id)

        ok = 0
        for path in files:
            try:
                upload_file(service, path, class_folder_id)
                ok += 1
                print(f"   ✔ {os.path.basename(path)}")
            except HttpError as e:
                print(f"   ✖ {os.path.basename(path)} — {e}")
        print(f"   Итого загружено: {ok}/{len(files)}")


def main():
    parser = argparse.ArgumentParser(description="Загрузка отчётов в папки классов на Google Диск.")
    parser.add_argument("--src", default=DEFAULT_SRC_DIR,
                        help="Локальная папка с отчётами (по умолчанию ./output)")
    parser.add_argument("--drive-root", default=DEFAULT_DRIVE_ROOT,
                        help="Имя корневой папки на Диске (игнорируется, если задан --root-id)")
    parser.add_argument("--parent-id", default=None,
                        help="ID родительской папки, если создаём корневую по имени")
    parser.add_argument("--root-id", default=None,
                        help="Использовать ЭТУ папку как корневую (ID). "
                             "Внутри неё будут созданы папки классов.")
    parser.add_argument("--all-files", action="store_true",
                        help="Грузить все файлы, не только .docx")
    args = parser.parse_args()

    if not os.path.isdir(args.src):
        raise SystemExit(f"Не найдена папка источника: {args.src}")

    run_upload(
        src_root=args.src,
        drive_root_name=args.drive_root,
        parent_id=args.parent_id,
        only_docx=(not args.all_files),
        root_id=args.root_id,
    )


if __name__ == "__main__":
    main()
