# Validation test workbooks

Файлы для TASK-010:

- `valid_workbook.xlsx` — корректный кейс (ожидается `summary.total = 0`).
- `problem_workbook.xlsx` — проблемный кейс (ожидаются `critical` и `warning` issues).

Ручная проверка JSON-вывода:

```bash
python - <<'PY'
import json
from validation.services import validate_workbook

for name in ["valid_workbook.xlsx", "problem_workbook.xlsx"]:
    path = f"validation/test_data/{name}"
    print(name)
    print(json.dumps(validate_workbook(path), ensure_ascii=False, indent=2))
PY
```