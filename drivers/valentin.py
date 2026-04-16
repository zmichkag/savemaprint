import socket
import time

# --- НАСТРОЙКИ ---
PRINTER_IP = "192.168.35.163"
PRINTER_PORT = 9100
TEMPLATE_NAME = "CZDM"  # Имя шаблона в памяти принтера (без расширения, зависит от настройки)
QUEUE_FIELD = "code"  # Имя поля (BM) для штрихкода/DataMatrix


class ValentinIndustrialDriver:
    # Управляющие символы ASCII по твоему стандарту
    SOH = b'\x01'
    STX = b'\x02'
    ETX = b'\x03'

    def __init__(self, ip, port=9100):
        self.ip = ip
        self.port = port

    def _send(self, command: str, data: str = "", expect_response: bool = True):
        """Низкоуровневая отправка команды CVPL с обрамлением"""
        cmd_b = command.encode('ascii')

        # Экранирование и кодировка данных
        data_b = b""
        if data:
            # Для кириллицы может потребоваться 'cp1251', для ЧЗ достаточно 'ascii'
            data_b = str(data).encode('ascii', errors='ignore')
            for char in [self.SOH, self.STX, self.ETX]:
                data_b = data_b.replace(char, b'')

        # Формирование кадра: [SOH] [CMD] [STX] [DATA] [ETX]
        frame = self.SOH + cmd_b
        if data_b:
            frame += self.STX + data_b
        frame += self.ETX

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.ip, self.port))
                s.sendall(frame)

                if expect_response:
                    response = s.recv(1024)
                    return response
                return b"OK"
        except Exception as e:
            return f"ERR_CONN: {e}".encode()

    # --- Слой команд управления ---

    def load_template(self, template_name):
        """Загрузка конкретного шаблона из памяти принтера (CF карты)"""
        # Команда FMB---r{имя_файла}
        res = self._send("FMB---r", template_name, expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def set_text_variable(self, field_name, value):
        """Установка статических полей (Text01, Text02 и т.д.)"""
        # Команда BV[{field_name}]{value}
        cmd = f"BV[{field_name}]"
        res = self._send(cmd, value, expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def append_queue(self, field_name, codes_list):
        """
        Заливка пачки кодов в очередь.
        Поскольку Valentin не имеет единой команды "загрузить массив",
        мы шлем пакет в одном TCP-соединении: [Переменная] -> [Печать 1 шт]
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.ip, self.port))

                for code in codes_list:
                    # 1. Записываем код ЧЗ в переменную
                    cmd_b = f"BV[{field_name}]".encode('ascii')
                    data_b = code.encode('ascii', errors='ignore')
                    frame_var = self.SOH + cmd_b + self.STX + data_b + self.ETX
                    s.sendall(frame_var)

                    # 2. Задаем тираж (1 шт) FBBA--r00001---
                    s.sendall(self.SOH + b"FBBA--r" + self.STX + b"00001---" + self.ETX)

                    # 3. Добавляем в очередь на печать (FBC)
                    s.sendall(self.SOH + b"FBC" + self.ETX)

                return "OK_QUEUED"
        except Exception as e:
            return f"ERR_CONN: {e}"

    def clear_queue(self, field_name=""):
        """Очистка очереди/сброс активных заданий"""
        # Команда FGA- отменяет задания в буфере
        res = self._send("FGA", "-", expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def start_print(self):
        """Для CVPL печать стартует автоматически при команде FBC из append_queue"""
        return "OK"

    def stop_print(self):
        """Остановка/пауза принтера"""
        # Команда FX ставит принтер на паузу
        res = self._send("FX", expect_response=False)
        return res.decode(errors='ignore') if isinstance(res, bytes) else res

    def get_status(self):
        """Запрос и расшифровка байта статуса CVPL"""
        resp = self._send("S", expect_response=True)
        if isinstance(resp, str) and resp.startswith("ERR"):
            return resp

        # Парсинг ответа принтера по спецификации (Стр. 97)
        if len(resp) >= 3 and resp[0:1] == self.SOH:
            byte1 = resp[1]
            if byte1 & 0x02: return "ERROR_RIBBON_OUT"
            if byte1 & 0x04: return "ERROR_PAPER_OUT"
            if byte1 & 0x08: return "ERROR_CUTTER"
            if byte1 & 0x20: return "PRINTING"
            return "READY"
        return "UNKNOWN"

    def get_capacity(self, field_name=""):
        """Количество оставшихся этикеток в очереди"""
        # SZA - запрос текущего счетчика и остатка
        resp = self._send("SZA", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_ribbon_remaining(self):
        """Остаток риббона в метрах (работает, если включен ribbon saver/measuring)"""
        resp = self._send("SM", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_total_prints(self):
        """Общий пробег (счетчик километров)"""
        # SL - статус работы (включает пробег печатающей головки)
        resp = self._send("SL", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp

    def get_firmware(self):
        """Версия прошивки"""
        # YX - Firmware version
        resp = self._send("YX", expect_response=True)
        return resp.decode(errors='ignore') if isinstance(resp, bytes) else resp


# --- БОЕВАЯ ЛОГИКА (Тест драйвера) ---

if __name__ == "__main__":
    printer = ValentinIndustrialDriver(PRINTER_IP, PRINTER_PORT)

    status = printer.get_status()
    print(f"[*] Проверка принтера Valentin... {status}")

    if "ERROR" in status:
        print("[!] Требуется вмешательство оператора. Остановка.")
        exit()

    # 1. Загружаем нужный шаблон
    print(f"[*] Загрузка шаблона {TEMPLATE_NAME}...")
    printer.load_template(TEMPLATE_NAME)

    # 2. Устанавливаем статику (партия, сроки)
    print("[*] Настройка текстовых полей...")
    printer.set_text_variable("Text01", "A2.C1.L7")
    printer.set_text_variable("Text02", "09.04.2026")
    printer.set_text_variable("Text03", "08.07.2026")

    # 3. Работаем с очередью кодов ЧЗ
    codes_from_1c = [
        "010461234567890121abc12345!91EE06!92abc1",
        "010461234567890121abc12345!91EE06!92abc2",
        "010461234567890121abc12345!91EE06!92abc3"
    ]

    print("[*] Сброс старой очереди...")
    printer.clear_queue()

    print(f"[*] Заливка {len(codes_from_1c)} кодов в очередь...")
    res = printer.append_queue(QUEUE_FIELD, codes_from_1c)

    if "OK" in res:
        print("[+] Коды успешно загружены. Принтер ждет сигнал датчика.")
    else:
        print(f"[-] ОШИБКА загрузки: {res}")

    # 5. Мониторинг
    cap = printer.get_capacity()
    print(f"[*] Ответ по счетчику принтера: {cap}")