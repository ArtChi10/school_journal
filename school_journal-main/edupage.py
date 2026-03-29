import os
from edupage_api import Edupage
from edupage_api.exceptions import BadCredentialsException, CaptchaException
from edupage_api.people import People, EduStudentSkeleton, EduStudent

EDUPAGE_USERNAME = os.getenv("EDUPAGE_USERNAME", "")
EDUPAGE_PASSWORD = os.getenv("EDUPAGE_PASSWORD", "")
EDUPAGE_SCHOOL = os.getenv("EDUPAGE_SCHOOL", "")

if not EDUPAGE_USERNAME or not EDUPAGE_PASSWORD or not EDUPAGE_SCHOOL:
    raise RuntimeError("Set EDUPAGE_USERNAME, EDUPAGE_PASSWORD and EDUPAGE_SCHOOL in environment")
edupage = Edupage()

try:
    edupage.login(EDUPAGE_USERNAME, EDUPAGE_PASSWORD, EDUPAGE_SCHOOL)
except BadCredentialsException:
    print("Wrong username or password!")
    raise
except CaptchaException:
    print("Captcha required!")
    raise

# 1. Берём "скелеты" всех студентов школы
skeletons: list[EduStudentSkeleton] = edupage.get_all_students() or []

# 2. Создаём объект People, привязанный к этому edupage
people_api = People(edupage)

full_students: list[EduStudent] = []

for s in skeletons:
    # 3. Пытаемся получить "полного" студента по person_id
    student = people_api.get_student(s.person_id)
    if student is not None:
        full_students.append(student)
    else:
        # get_student ищет только среди get_students(),
        # так что кого-то он может не найти
        print(f"⚠ Не нашёл полного студента для id={s.person_id}, оставляю скелет ({s.name_short})")

# 4. Выводим информацию о найденных полноценных EduStudent
for st in full_students:
    print(
        f"id={st.person_id}, name={st.name}, "
        f"class_id={st.class_id}, number_in_class={st.number_in_class}"
    )
