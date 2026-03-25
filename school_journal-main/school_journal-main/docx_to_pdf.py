# -*- coding: utf-8 -*-
"""
Простой конвертер DOCX -> PDF.

Примеры:
  # один файл -> рядом PDF
  python docx_to_pdf.py --file "output/4A/Иванов Иван.docx"

  # папка рекурсивно -> рядом PDF
  python docx_to_pdf.py --src output

  # папка рекурсивно -> в другую папку (с сохранением структуры)
  python docx_to_pdf.py --src output --dst pdf_out
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional

from docx2pdf import convert as docx2pdf_convert


def convert_single(docx_path: Path, pdf_path: Optional[Path] = None) -> bool:
    """
    Конвертирует один DOCX в PDF.
    Если pdf_path не указан, кладёт рядом с DOCX (same name, .pdf).
    Возвращает True при успехе.
    """
    try:
        if pdf_path is None:
            pdf_path = docx_path.with_suffix(".pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # docx2pdf умеет писать по каталогу назначения.
        # Конвертируем в целевую папку, затем переименуем точное имя.
        tmp_dir = pdf_path.parent
        before = set(p.name for p in tmp_dir.glob("*.pdf"))
        docx2pdf_convert(str(docx_path), str(tmp_dir))
        after = set(p.name for p in tmp_dir.glob("*.pdf"))
        new_pdfs = list(after - before)

        # Обычно Word делает <stem>.pdf, проверим его в первую очередь.
        candidate = tmp_dir / (docx_path.stem + ".pdf")
        produced = None
        if candidate.exists():
            produced = candidate
        elif new_pdfs:
            produced = tmp_dir / new_pdfs[0]

        if produced is None or not produced.exists():
            print(f"✖ Не удалось найти PDF после конвертации: {docx_path}")
            return False

        # Переместим в нужное имя, если отличается
        if produced.resolve() != pdf_path.resolve():
            if pdf_path.exists():
                pdf_path.unlink()
            produced.replace(pdf_path)

        print(f"✔ {docx_path.name} -> {pdf_path}")
        return True
    except Exception as e:
        print(f"✖ Ошибка DOCX->PDF для {docx_path}: {e}")
        return False


def convert_tree(src_dir: Path, dst_dir: Optional[Path] = None) -> None:
    """
    Рекурсивно конвертирует все .docx из src_dir.
    Если dst_dir задана — сохраняет pdf в неё, повторяя структуру каталогов.
    Иначе — кладёт pdf рядом с каждым docx.
    """
    docs = list(src_dir.rglob("*.docx"))
    if not docs:
        print(f"В {src_dir} не найдено .docx файлов.")
        return

    total = len(docs)
    ok = 0
    print(f"Найдено DOCX: {total} (включая подпапки)")

    for i, docx_path in enumerate(docs, 1):
        rel = docx_path.relative_to(src_dir)
        if dst_dir:
            pdf_path = (dst_dir / rel).with_suffix(".pdf")
        else:
            pdf_path = None  # рядом

        print(f"[{i}/{total}] {rel}")
        if convert_single(docx_path, pdf_path):
            ok += 1

    print(f"\nГотово: {ok}/{total} успешно конвертировано.")


def main():
    ap = argparse.ArgumentParser(description="Конвертация DOCX -> PDF (один файл или папка рекурсивно).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="Путь к одному .docx файлу")
    g.add_argument("--src", help="Папка с .docx (рекурсивно)")

    ap.add_argument("--dst", help="Папка для сохранения PDF (опционально). Если не указана — рядом с DOCX.")

    args = ap.parse_args()

    if args.file:
        docx = Path(args.file).resolve()
        if not docx.is_file():
            print(f"Файл не найден: {docx}")
            sys.exit(1)
        pdf: Optional[Path] = None
        if args.dst:
            dst = Path(args.dst).resolve()
            dst.mkdir(parents=True, exist_ok=True)
            pdf = (dst / docx.name).with_suffix(".pdf")
        success = convert_single(docx, pdf)
        sys.exit(0 if success else 2)

    if args.src:
        src_dir = Path(args.src).resolve()
        if not src_dir.is_dir():
            print(f"Папка не найдена: {src_dir}")
            sys.exit(1)

        dst_dir: Optional[Path] = None
        if args.dst:
            dst_dir = Path(args.dst).resolve()
            dst_dir.mkdir(parents=True, exist_ok=True)

        convert_tree(src_dir, dst_dir)
        sys.exit(0)


if __name__ == "__main__":
    main()
