import requests
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("BrainServerDriver")


class BizerbaBRAIN2Driver:
    """
    Драйвер для работы с весами Bizerba через WCF-сервис _connect.BRAIN.
    Опирается на методы SendMessage и ReceiveMessage (очередь DUSTBIN).
    """

    def __init__(self, server_ip: str, port: int = 2020, device_name: str = "TEST"):

        self.base_url = f"http://{server_ip}:{port}/ConnectService/json"
        self.device_name = device_name
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def _send_post(self, method_name: str, payload: dict) -> dict:
        """Базовый метод отправки запросов к WCF-сервису Bizerba."""
        url = f"{self.base_url}/{method_name}"
        try:
            response = self.session.post(url, json=payload, timeout=5.0)
            response.raise_for_status()

            # WCF оборачивает ответ в корневой ключ "d"
            data = response.json()
            return data.get("d", data)

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Ошибка [{method_name}]: {e.response.status_code} - {e.text}")
            return {}
        except Exception as e:
            logger.error(f"Системная ошибка [{method_name}]: {e}")
            return {}

    def _send_gxnet_command(self, header: str, data: str = "") -> bool:
        """Обертка для отправки низкоуровневых команд GxNet через SendMessage."""
        # Формируем сообщение по стандарту GX (A!Заголовок\r\nДанные)
        message = f"A!{header}\r\n"
        if data:
            message += f"{data}\r\n"

        payload = {
            "connectName": self.device_name,
            "message": message,
            "timeout": 2000  # Таймаут в мс, согласно мануалу
        }

        res = self._send_post("SendMessage", payload)

        # Проверяем статус (0: OK, 1: Timeout, 2: Next) - из мануала
        status = res.get("Status")
        if status == 0:
            return True
        else:
            logger.error(f"Ошибка отправки команды (Status: {status})")
            return False

    def load_plu(self, plu_number: str) -> bool:
        """Установка артикула (PLU)."""
        logger.info(f"Запрос на установку PLU {plu_number} для {self.device_name}...")
        return self._send_gxnet_command("GL19", plu_number)

    def push_code_to_buffer(self, seq_id: str, datamatrix: str) -> bool:
        """Запись DataMatrix и Индекса в переменные весов."""
        header = "LV01|GT05|GV50|LX02"
        data = f"{datamatrix}|{seq_id}"
        logger.info(f"Загрузка кода [ID: {seq_id}] в буфер...")
        return self._send_gxnet_command(header, data)

    def poll_weight_telegrams(self) -> list:
        """
        Опрос сервера на наличие спонтанных сообщений (оттисков веса).
        Обращается к системной очереди DUSTBIN.
        """
        payload = {
            "connectName": self.device_name,
            "handle": "DUSTBIN",  # Стандартная очередь для спонтанных данных
            "timeout": 1000,  # Ждем 1 секунду
            "sendAck": True  # Подтверждаем получение, чтобы сервер удалил сообщение
        }

        res = self._send_post("ReceiveMessage", payload)
        telegrams = []

        # Если статус 0 (OK) и есть строка ответа
        if res.get("Status") == 0 and res.get("Response"):
            raw_response = res.get("Response")
            # Разбираем пакеты, разделенные \r\n
            lines = raw_response.split('\r\n')
            for line in lines:
                if "PD00" in line and "GV50" in line:
                    telegrams.append(line)

        return telegrams