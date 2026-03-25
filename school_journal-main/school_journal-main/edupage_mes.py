import json
import uuid
import requests

def send_private_message_raw(session: requests.Session,
                             chatid: int,
                             text: str,
                             uid: str,
                             uidsgn: str,
                             opened_timestamp: str):
    """
    Полный клон браузерного запроса Edookit ChatList.
    Отправляет сообщение в личный чат.
    """

    # 1. Делаем randid + key такие же, как делает браузер
    randid = uuid.uuid4().hex.upper()[:20]
    key = f"chatsprava_{randid}"

    # 2. actions — точная структура
    actions = {
        key: {
            "type": "chatsprava",
            "text": text,
            "chatid": chatid,
            "key": key,
            "randid": randid
        }
    }

    # 3. URL с точными Query-параметрами
    url = (
        "https://projector.edupage.org/chat/quick"
        "?cmd=ChatList"
        "&t=2025-11-19 21:47:56"
        "&e=projector"
    )

    # 4. Формируем тело запроса
    payload = {
        "akcia": "sync",
        "openedChats": f"{chatid}|{opened_timestamp}",
        "uid": uid,
        "uidsgn": uidsgn,
        "actions": json.dumps(actions, ensure_ascii=False)
    }

    print("=== Request Body ===")
    print(json.dumps(payload, indent=4, ensure_ascii=False))

    # 5. Отправляем
    resp = session.post(url, data=payload)
    print("=== Response ===")
    print(resp.text)

    data = resp.json()

    # 6. Проверяем OK
    if data.get("actionsRes", {}).get(key) != "ok":
        raise RuntimeError(f"Сообщение НЕ отправлено: {data}")

    print("Сообщение успешно отправлено!")
    return data

from edupage_api import Edupage

ed = Edupage()
ed.login("artchibisov10@gmail.com", "Ilovemomforever4!", "projector")

chatid = 5237
opened_timestamp = "2025-11-19 21:27:44"

send_private_message_raw(
    session=ed.session,
    chatid=chatid,
    text="Привет! Это сообщение отправлено через API 😊",
    uid="Ucitel-218 ",
    uidsgn="962cdcdfb19dec0ff6e595d4af1e807372127947cc18aecbe96d0d1f413f5651",
    opened_timestamp=opened_timestamp
)
