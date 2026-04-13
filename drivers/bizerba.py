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

    def __init__(self, device_name: str = "TEST"):

        # self.base_url = f"http://{server_ip}:{port}/ConnectService/json"
        self.base_url = f"http://brain2:2020/ConnectService/json"
        self.device_name = device_name
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def _send_get(self, method_name: str, params: dict = None) -> dict:
        """Отправка GET-запроса с 'сырым' URL для обхода кодировки Bizerba."""
        # 1. Базовая часть URL
        url = f"{self.base_url}/{method_name}"

        # 2. Собираем строку параметров вручную, БЕЗ кодировки спецсимволов
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{url}?{query_string}"
        else:
            full_url = url

        # 3. Выводим в лог точный URL, который улетает в сеть
        logger.info(f"[DEBUG] RAW URL: {full_url}")

        try:
            # Отправляем строку напрямую. Requests не будет ее перекодировать.
            response = self.session.get(full_url, timeout=5.0)
            response.raise_for_status()

            data = response.json()
            return data.get("d", data)

        except requests.exceptions.HTTPError as e:
            err_text = e.response.text if e.response else "No response text"
            logger.error(f"HTTP Ошибка. URL: {full_url} | Ответ: {err_text}")
            return {}
        except Exception as e:
            logger.error(f"Системная ошибка: {e}")
            return {}

    def receive_message(self, handle: str, timeout: int = 2000) -> dict:
        """
        Второй этап: получение данных по дескриптору (handle).
        """
        params = {
            "connectName": self.device_name,
            "handle": handle,
            "timeout": timeout,
            "sendAck": "true"  # Подтверждаем получение [cite: 116]
        }
        # Используем метод GET, как в твоем успешном тесте [cite: 32]
        return self._send_get("ReceiveMessage", params=params)

    def ask_and_receive(self, cmd_type: str, command: str, data: str = "") -> dict:
        """
        Полный цикл: SendMessage -> Получение Handle -> ReceiveMessage.
        """
        # 1. Формируем команду (например, A?GL19|0)
        pfx = "A?" if cmd_type.lower() == 'r' else "A!"
        message = f"{pfx}{command}"
        if data:
            message += f"|{data}"

        # 2. Этап 1: SendMessage
        logger.info(f"[*] Шаг 1: Отправка команды {message}")
        send_res = self._send_get("SendMessage", params={
            "connectName": self.device_name,
            "message": message,
            "timeout": 2000
        })

        handle = send_res.get("Response")
        status = send_res.get("Status")

        # Если статус OK или Timeout (но handle пришел), идем за данными [cite: 211]
        if handle and (status in [1, 2]):
            logger.info(f"[*] Шаг 2: ReceiveMessage по Handle: {handle}")

            # Небольшая пауза, чтобы весы прожевали команду
            time.sleep(0.1)

            # Вызываем второй метод для получения реального ответа
            return self.receive_message(handle)

            # Если статуса 1 или 2 нет, возвращаем что есть (возможно это уже ошибка или OK)
        return send_res

    def create_queue(self) -> str:
        """Создает именованную очередь для устройства и возвращает её имя."""
        params = {"connectName": self.device_name}
        res = self._send_get("CreateReceiveQueue", params=params)
        # Возвращает имя созданной очереди [cite: 61]
        return res.get("Response", "")

    def set_queue_filter(self, queue_name: str, filter_str: str = "PV"):
        """Настраивает фильтр, чтобы в очередь попадал только вес (PV)[cite: 161, 168]."""
        params = {
            "connectName": self.device_name,
            "queueName": queue_name,
            "filter": filter_str
        }
        return self._send_get("SetReceiveQueueFilter", params=params)

    def receive_from_queue(self, queue_name: str, timeout: int = 1000) -> list:
        """Вычитывает пачку накопившихся сообщений из конкретной очереди[cite: 112, 116]."""
        params = {
            "connectName": self.device_name,
            "handle": queue_name,
            "timeout": timeout,
            "sendAck": "true"  # Подтверждаем получение, чтобы очистить очередь
        }
        res = self._send_get("ReceiveMessage", params=params)

        telegrams = []
        if res.get("Status") in [0, 2]:  # 0 - ОК, 2 - есть еще данные [cite: 211]
            raw_data = res.get("Response", "")
            if raw_data:
                # Разрезаем пачку на отдельные телеграммы
                telegrams = [t for t in raw_data.split('\r\n') if t]

        return telegrams

    def _send_gxnet_command(self, type: str, header: str, data: str = "") -> dict:
        """Обертка для отправки низкоуровневых команд GxNet через SendMessage (GET)."""
        pfx = "!" if type == "w" else "?"

        # Собираем сообщение. Оставляем \r\n, т.к. requests автоматически
        # закодирует их в %0D%0A для URL, как того требует HTTP.
        message = f"A{pfx}{header}\r\n"
        if data:
            message += f"{data}\r\n"

        params = {
            "connectName": self.device_name,
            "message": message,
            "timeout": 2000  # Таймаут в мс
        }

        # Вызываем через GET!
        res = self._send_get("SendMessage", params=params)

        status = res.get("Status")
        if status not in [0, 1]:  # 0: OK, 1: Timeout (часто бывает при чтении)
            logger.warning(f"Сервер вернул статус: {status} для команды {header}")

        return res

    def get_active_scales(self) -> list:
        """
        Запрашивает список оборудования через GetConnectInfo и фильтрует только весы.
        """
        logger.info("Запрос топологии оборудования (GetConnectInfo)...")

        raw_data = self._send_get("GetConnectInfo")

        devices = raw_data if isinstance(raw_data, list) else []

        if not devices:
            logger.warning("Сервер вернул пустой список или данные не удалось распарсить.")
            return []

        target_scales = []

        for dev in devices:
            dev_type = dev.get("Type")
            name = dev.get("Name")
            state = dev.get("State")

            # Фильтруем: 19 = GLP, 35 = GLM-I
            if dev_type in [19, 35]:
                is_active = (state == 0)

                target_scales.append({
                    "name": name,
                    "type": dev_type,
                    "is_active": is_active,
                    "supports_spontaneous": dev.get("ConnectionWithSpontaneousData", False)
                })

        logger.info(f"Найдено целевых весов (GLP/GLM-I): {len(target_scales)}")
        return target_scales

    def load_plu(self, plu_number: str) -> bool:
        """Установка артикула (PLU)."""
        logger.info(f"Запрос на установку PLU {plu_number} для {self.device_name}...")
        header = "LV01|GL19|LX02"
        return self._send_gxnet_command("r", header, plu_number)

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