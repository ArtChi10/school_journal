import json
import subprocess
from pathlib import Path

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCRIPT = REPO_ROOT / "school_journal-main" / "main.py"


@require_GET
def healthcheck(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_POST
def run_pipeline(request: HttpRequest) -> JsonResponse:
    payload = json.loads(request.body or "{}")
    dry_run = bool(payload.get("dry_run", False))

    if not LEGACY_SCRIPT.exists():
        return JsonResponse(
            {"status": "error", "message": f"Legacy script not found: {LEGACY_SCRIPT}"},
            status=500,
        )

    if dry_run:
        return JsonResponse({"status": "ok", "mode": "dry_run", "script": str(LEGACY_SCRIPT)})

    result = subprocess.run(
        ["python", str(LEGACY_SCRIPT)],
        cwd=str(LEGACY_SCRIPT.parent),
        capture_output=True,
        text=True,
        check=False,
    )

    return JsonResponse(
        {
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        },
        status=200 if result.returncode == 0 else 500,
    )