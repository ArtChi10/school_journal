from edupage_api import Edupage
from edupage_api.exceptions import BadCredentialsException, CaptchaException
from edupage_api.people import EduTeacher

edupage = Edupage()

try:
    edupage.login("artchibisov10@gmail.com", "Ilovemomforever4!", "projector")
except BadCredentialsException:
    print("Wrong username or password!")
    exit()
except CaptchaException:
    print("Captcha required!")
    exit()

# ID учителя, которого ищем
target_id = "Teacher-122"   # из Teacher-122 → 122

teachers = edupage.get_teachers()

found = None
for t in teachers:
    # get_id() всегда число
    if t.get_id() == target_id:
        found = t
        break

if found:
    print(f"Найден человек с ID {target_id}: {found.name}")
else:
    print(f"Человек с ID {target_id} НЕ найден среди учителей.")
