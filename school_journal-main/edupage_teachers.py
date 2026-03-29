import os
from edupage_api import Edupage
from edupage_api.exceptions import BadCredentialsException, CaptchaException

EDUPAGE_USERNAME = os.getenv("EDUPAGE_USERNAME", "")
EDUPAGE_PASSWORD = os.getenv("EDUPAGE_PASSWORD", "")
EDUPAGE_SCHOOL = os.getenv("EDUPAGE_SCHOOL", "")
TARGET_TEACHER_ID = os.getenv("EDUPAGE_TARGET_TEACHER_ID", "")

if not EDUPAGE_USERNAME or not EDUPAGE_PASSWORD or not EDUPAGE_SCHOOL:
    raise RuntimeError("Set EDUPAGE_USERNAME, EDUPAGE_PASSWORD and EDUPAGE_SCHOOL in environment")
if not TARGET_TEACHER_ID:
    raise RuntimeError("Set EDUPAGE_TARGET_TEACHER_ID in environment")

edupage = Edupage()

try:
    edupage.login(EDUPAGE_USERNAME, EDUPAGE_PASSWORD, EDUPAGE_SCHOOL)
except BadCredentialsException:
    print("Wrong username or password!")
    exit()
except CaptchaException:
    print("Captcha required!")
    exit()

# ID учителя, которого ищем
target_id = TARGET_TEACHER_ID

teachers = edupage.get_teachers()

found = None
for t in teachers:
    if t.get_id() == target_id:
        found = t
        break

if found:
    print(f"Найден человек с ID {target_id}: {found.name}")
else:
    print(f"Человек с ID {target_id} НЕ найден среди учителей.")
