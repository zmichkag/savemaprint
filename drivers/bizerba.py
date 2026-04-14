import requests
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("BrainServerDriver")


class BizerbaBRAIN2Driver:
    """     Драйвер для работы с весами Bizerba через rest API connect.BRAIN     """

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
        """Отправка GET-запроса с сырым URL для обхода кодировки Bizerba."""
        # базовый URL
        url = f"{self.base_url}/{method_name}"

        # сырая строка, по тому что фаст апи умный а BRAIN умных не любит
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{url}?{query_string}"
        else:
            full_url = url

        #на всякий случай смотрим куда ходидли
        logger.info(f"[DEBUG] RAW URL: {full_url}")

        try:
            #отправляем строку
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
        """ Получаем ответ по хэндлу  """
        params = {
            "connectName": self.device_name,
            "handle": handle,
            "timeout": timeout,
            "sendAck": "true"
        }

        return self._send_get("ReceiveMessage", params=params)

    def ask_and_receive(self, cmd_type: str, command: str, data: str = "") -> dict:
        """ Полный контакт: запрос - хендл - ответ         """
        # Собираем клманду
        pfx = "A?" if cmd_type.lower() == 'r' else "A!"
        message = f"{pfx}{command}"
        if data:
            message += f"|{data}"

        # SendMessage
        logger.info(f"[*] Шаг 1: Отправка команды {message}")
        send_res = self._send_get("SendMessage", params={
            "connectName": self.device_name,
            "message": message,
            "timeout": 2000
        })

        handle = send_res.get("Response")
        status = send_res.get("Status")

        # Если статус OK или Timeout + handle, мсмотрим что там по хендлу (вдруг там что-то важное)
        if handle and (status in [1, 2]):
            logger.info(f"[*] Шаг 2: ReceiveMessage по Handle: {handle}")

            # даем время подумать
            time.sleep(0.1)

            # шлем хендл, читаем ответ
            return self.receive_message(handle)

            # в любом другом случае, возвращаем ответ.
        return send_res

    def create_queue(self) -> str:
        """Создает очередь """
        params = {"connectName": self.device_name}
        res = self._send_get("CreateReceiveQueue", params=params)
        return res.get("Response", "")

    def set_queue_filter(self, queue_name: str, filter_str: str = "PV"):
        """Делаем фильтр - только вес (PV) """
        params = {
            "connectName": self.device_name,
            "queueName": queue_name,
            "filter": filter_str
        }
        return self._send_get("SetReceiveQueueFilter", params=params)

    def receive_from_queue(self, queue_name: str, timeout: int = 1000) -> list:
        """читаем очередь"""
        params = {
            "connectName": self.device_name,
            "handle": queue_name,
            "timeout": timeout,
            "sendAck": "true"
        }
        res = self._send_get("ReceiveMessage", params=params)

        telegrams = []
        if res.get("Status") in [0, 2]:  # 0 - ОК, 2 - есть еще данные [cite: 211]
            raw_data = res.get("Response", "")
            if raw_data:
                # разбираем очередь.
                telegrams = [t for t in raw_data.split('\r\n') if t]

        return telegrams

    def _send_gxnet_command(self, type: str, header: str, data: str = "") -> dict:
        """Обертка для отправки низкоуровневых команд GxNet через SendMessage (GET)."""
        pfx = "!" if type == "w" else "?"

        message = f"A{pfx}{header}\r\n"
        if data:
            message += f"{data}\r\n"

        params = {
            "connectName": self.device_name,
            "message": message,
            "timeout": 2000  # Таймаут в мс
        }


        res = self._send_get("SendMessage", params=params)

        status = res.get("Status")
        if status not in [0, 1]:  # 0: OK, 1: Timeout (часто бывает при чтении)
            logger.warning(f"Сервер вернул статус: {status} для команды {header}")

        return res

    def get_active_scales(self) -> list:
        """         Список устройств         """
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

            # Фильтруем 19 = GLP, 35 = GLM-I, остальное не трогаем, оно всеравно нихрена не умеет
            if dev_type in [19, 35]:
                is_active = (state == 0)

                target_scales.append({
                    "name": name,
                    "type": dev_type,
                    "is_active": is_active,
                    "supports_spontaneous": dev.get("ConnectionWithSpontaneousData", False)
                })

        logger.info(f"Найдено весов (GLP/GLM-I): {len(target_scales)}")
        return target_scales

    def load_plu(self, plu_number: str) -> bool:
        """Установка PLU"""
        logger.info(f"Запрос на установку PLU {plu_number} для {self.device_name}...")
        header = "LV01|GL19|LX02"
        return self._send_gxnet_command("r", header, plu_number)

    def push_code_to_buffer(self, seq_id: str, datamatrix: str) -> bool:
        """Запись ЧЗ и Индекса в бицербы ."""
        header = "LV01|GT05|GV50|LX02"
        data = f"{datamatrix}|{seq_id}"
        logger.info(f"Загрузка кода [ID: {seq_id}] в буфер...")
        return self._send_gxnet_command(header, data)

    def poll_weight_telegrams(self) -> list:
        """  это не работает пока    """
        payload = {
            "connectName": self.device_name,
            "handle": "DUSTBIN",
            "timeout": 1000,
            "sendAck": True
        }

        res = self._send_post("ReceiveMessage", payload)
        telegrams = []

        # Если статус 0 + строка ответа
        if res.get("Status") == 0 and res.get("Response"):
            raw_response = res.get("Response")
            # Разбираем пакеты
            lines = raw_response.split('\r\n')
            for line in lines:
                if "PD00" in line and "GV50" in line:
                    telegrams.append(line)

        return telegrams