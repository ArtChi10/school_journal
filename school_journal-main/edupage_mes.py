import json
import os
import uuid
import requests
from edupage_api import Edupage


EDUPAGE_USERNAME = os.getenv("EDUPAGE_USERNAME", "")
EDUPAGE_PASSWORD = os.getenv("EDUPAGE_PASSWORD", "")
EDUPAGE_SCHOOL = os.getenv("EDUPAGE_SCHOOL", "")
EDUPAGE_CHAT_ID = os.getenv("EDUPAGE_CHAT_ID", "")
EDUPAGE_OPENED_TIMESTAMP = os.getenv("EDUPAGE_OPENED_TIMESTAMP", "")
EDUPAGE_UID = os.getenv("EDUPAGE_UID", "")
EDUPAGE_UIDSGN = os.getenv("EDUPAGE_UIDSGN", "")
EDUPAGE_TEST_MESSAGE = os.getenv("EDUPAGE_TEST_MESSAGE", "Привет! Это сообщение отправлено через API 😊")


if not all([
    EDUPAGE_USERNAME,
    EDUPAGE_PASSWORD,
    EDUPAGE_SCHOOL,
    EDUPAGE_CHAT_ID,
    EDUPAGE_OPENED_TIMESTAMP,
    EDUPAGE_UID,
    EDUPAGE_UIDSGN,
]):
    raise RuntimeError(
        "Set EDUPAGE_USERNAME, EDUPAGE_PASSWORD, EDUPAGE_SCHOOL, EDUPAGE_CHAT_ID, "
        "EDUPAGE_OPENED_TIMESTAMP, EDUPAGE_UID and EDUPAGE_UIDSGN in environment"
    )

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

    randid = uuid.uuid4().hex.upper()[:20]
    key = f"chatsprava_{randid}"

    actions = {
        key: {
            "type": "chatsprava",
            "text": text,
            "chatid": chatid,
            "key": key,
            "randid": randid
        }
    }

    url = (
        f"https://{EDUPAGE_SCHOOL}.edupage.org/chat/quick"
        "?cmd=ChatList"
        "&t=2025-11-19 21:47:56"
        f"&e={EDUPAGE_SCHOOL}"
    )

    payload = {
        "akcia": "sync",
        "openedChats": f"{chatid}|{opened_timestamp}",
        "uid": uid,
        "uidsgn": uidsgn,
        "actions": json.dumps(actions, ensure_ascii=False)
    }

    print("=== Request Body ===")
    print(json.dumps(payload, indent=4, ensure_ascii=False))

    resp = session.post(url, data=payload)
    print("=== Response ===")
    print(resp.text)

    data = resp.json()

    if data.get("actionsRes", {}).get(key) != "ok":
        raise RuntimeError(f"Сообщение НЕ отправлено: {data}")

    print("Сообщение успешно отправлено!")
    return data

ed = Edupage()
ed.login(EDUPAGE_USERNAME, EDUPAGE_PASSWORD, EDUPAGE_SCHOOL)


send_private_message_raw(
    session=ed.session,
    chatid=int(EDUPAGE_CHAT_ID),
    text=EDUPAGE_TEST_MESSAGE,
    uid=EDUPAGE_UID,
    uidsgn=EDUPAGE_UIDSGN,
    opened_timestamp=EDUPAGE_OPENED_TIMESTAMP,
)
