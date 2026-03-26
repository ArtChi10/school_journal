"""Validation rules for descriptor workbooks."""

ALLOWED_DESCRIPTOR_VALUES = {
    "Не проявляется | Not evident (0-39%)",
    "Начальный уровень | Beginner level (40-49%)",
    "Соответствует ожиданиям по программе | Meets expectations (50-89%)",
    "Превосходит ожидания по программе | Exceeds expectations (90-100%)",
    # если в реальных таблицах есть новые формулировки — добавим
    "Пока не выполняет | Not Yet Able",
    "Пока не может сам, но может с помощью учителя | Needs Assistance",
    "Выполняет самостоятельно | Independent",
    "Выполняет основное и дополнительное задание | Proficient",
}

REQUIRED_HEADER_KEYS = [
    "class",  # Класс | Grade
    "teacher",  # Учитель | Teacher
    "module",  # Учебный модуль
    "descriptor",  # Дескриптор
]

TEST_SCORE_MIN = 0
TEST_SCORE_MAX = 100

# пока MVP: комментарий обязателен если есть низкий результат
LOW_SCORE_THRESHOLD = 50
COMMENT_REQUIRED_IF_LOW_SCORE = True
RETAKE_REQUIRED_IF_LOW_SCORE = True