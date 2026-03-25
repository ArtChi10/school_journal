# gsheet_reader.py
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
import csv

def _csv_export_url(google_edit_url: str) -> str:
    """
    Превращает ссылку вида
    https://docs.google.com/spreadsheets/d/<ID>/edit?...#gid=<GID>
    в
    https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=<GID>
    """
    u = urlparse(google_edit_url)
    parts = u.path.strip("/").split("/")
    # ожидаем .../spreadsheets/d/<ID>/...
    try:
        i = parts.index("d")
        sheet_id = parts[i+1]
    except Exception:
        raise ValueError("Не удалось извлечь spreadsheet ID из ссылки")

    # gid может быть во фрагменте (#gid=...) или в query (?gid=...)
    gid = None
    if u.fragment:
        frag_qs = parse_qs(u.fragment)
        gid = (frag_qs.get("gid") or [None])[0]
    if not gid:
        qs = parse_qs(u.query)
        gid = (qs.get("gid") or [None])[0]
    if not gid:
        # по умолчанию первая вкладка = gid 0
        gid = "0"

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

def read_class_links_from_gsheet(google_edit_url: str) -> dict[str, str]:
    """
    Читает Google Sheet (2 колонки: Class, link) и возвращает словарь:
    {<название класса>: <ссылка>}
    Также печатает словарь в консоль.
    """
    url = _csv_export_url(google_edit_url)
    with urlopen(url) as resp:
        data = resp.read().decode("utf-8", errors="replace")

    # Парсим CSV (первая строка — заголовки)
    reader = csv.DictReader(data.splitlines())
    # допускаем разные регистры/языки заголовков
    def norm_key(k: str) -> str: return (k or "").strip().lower()

    # сопоставим реальные имена колонок
    fieldnames = {norm_key(k): k for k in reader.fieldnames or []}
    class_col = fieldnames.get("class") or fieldnames.get("класс")
    link_col  = fieldnames.get("link")  or fieldnames.get("ссылка")

    if not class_col or not link_col:
        raise ValueError(f"В таблице не найдены колонки 'Class' и 'link'. Нашли: {reader.fieldnames}")

    result: dict[str, str] = {}
    for row in reader:
        cls = (row.get(class_col) or "").strip()
        href = (row.get(link_col)  or "").strip()
        if cls and href:
            result[cls] = href

    print("Class → link dict:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return result
