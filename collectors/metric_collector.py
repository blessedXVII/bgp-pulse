from __future__ import annotations
import asyncio
import re
import logging
import puresnmp
import time
from collections import deque
import socketserver
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


async def measure_latency(target_host: str, count: int = 10) -> float | None:
    """Замерить средний RTT до хоста через ping.

    Args:
        target_host: IP-адрес цели.
        count: Количество ICMP-пакетов.

    Returns:
        Средний RTT в миллисекундах или None если хост недоступен.
    """
    cmd = ["ping", "-c", str(count), "-W", "2", target_host]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=count * 3)

        if proc.returncode not in (0, 1):
            logger.warning("ping до %s завершился с ошибкой", target_host)
            return None

        return _parse_rtt(stdout.decode())

    except asyncio.TimeoutError:
        logger.warning("ping до %s: таймаут", target_host)
        return None


def _parse_rtt(output: str) -> float | None:
    """Извлечь средний RTT из вывода ping.

    Args:
        output: Текст вывода команды ping.

    Returns:
        Средний RTT в миллисекундах или None если не удалось распарсить.
    """
    match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", output)
    if not match:
        logger.warning("Не удалось распарсить RTT из вывода ping")
        return None
    return float(match.group(1))


def normalize_latency(rtt_ms: float, max_rtt_ms: float = 200.0) -> float:
    """Нормировать RTT в метрику m2 (0..1, где 1 = лучшее).

    Args:
        rtt_ms: Средний RTT в миллисекундах.
        max_rtt_ms: RTT при котором m2 = 0. Задаётся в конфиге.

    Returns:
        m2 в диапазоне [0.0, 1.0].
    """
    return max(0.0, 1.0 - rtt_ms / max_rtt_ms)


# OID счётчиков байт на интерфейсе
OID_IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"   # входящие байты
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"  # исходящие байты


async def _snmp_get(host: str, oid: str) -> int | None:
    """Получить одно значение с роутера по SNMP.

    Args:
        host: IP-адрес роутера.
        oid: OID нужного счётчика в виде строки.

    Returns:
        Целое число или None если запрос не удался.
    """
    try:
        client = puresnmp.PyWrapper(puresnmp.Client(host, puresnmp.V2C("public")))
        result = await client.get(oid)
        return int(result)
    except Exception as exc:
        logger.warning("SNMP ошибка для %s %s: %s", host, oid, exc)
        return None


async def measure_load(
    host: str,
    if_index: int,
    max_bandwidth_bps: float,
    interval_sec: float = 1.0,
) -> float | None:
    """Замерить загрузку интерфейса через SNMP (два снимка с интервалом).

    Args:
        host: IP-адрес роутера.
        if_index: Индекс интерфейса (ifIndex). Для Ethernet0/0 = 1.
        max_bandwidth_bps: Максимальная пропускная способность в бит/с.
        interval_sec: Интервал между снимками в секундах.

    Returns:
        Утилизация канала 0..1 или None если SNMP недоступен.
    """
    oid_in = f"{OID_IF_IN_OCTETS}.{if_index}"
    oid_out = f"{OID_IF_OUT_OCTETS}.{if_index}"

    # Первый снимок
    in1 = await _snmp_get(host, oid_in)
    out1 = await _snmp_get(host, oid_out)

    if in1 is None or out1 is None:
        return None

    await asyncio.sleep(interval_sec)

    # Второй снимок
    in2 = await _snmp_get(host, oid_in)
    out2 = await _snmp_get(host, oid_out)

    if in2 is None or out2 is None:
        return None

    # Скорость в битах/с (октеты * 8)
    speed_bps = ((in2 - in1) + (out2 - out1)) * 8 / interval_sec

    return min(1.0, speed_bps / max_bandwidth_bps)


def normalize_load(utilization: float) -> float:
    """Нормировать утилизацию в метрику m1 (0..1, где 1 = лучшее).

    Args:
        utilization: Утилизация канала 0..1 (0 = пустой, 1 = полный).

    Returns:
        m1 = 1 - утилизация.
    """
    return 1.0 - utilization

# OID счётчиков ошибок и дропов
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"    # входящие ошибки
OID_IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13"  # входящие дропы
OID_IF_IN_UCAST = "1.3.6.1.2.1.2.2.1.11"     # входящие пакеты (всего)


async def measure_loss(
    host: str,
    if_index: int,
    interval_sec: float = 1.0,
) -> float | None:
    """Замерить потери пакетов на интерфейсе через SNMP.

    Считает долю ошибочных и дропнутых пакетов от общего числа
    за интервал между двумя снимками.

    Args:
        host: IP-адрес роутера.
        if_index: Индекс интерфейса (ifIndex).
        interval_sec: Интервал между снимками в секундах.

    Returns:
        Доля потерь 0..1 или None если SNMP недоступен.
        0.0 = нет потерь, 1.0 = все пакеты потеряны.
    """
    oid_errors = f"{OID_IF_IN_ERRORS}.{if_index}"
    oid_discards = f"{OID_IF_IN_DISCARDS}.{if_index}"
    oid_ucast = f"{OID_IF_IN_UCAST}.{if_index}"

    # Первый снимок
    err1 = await _snmp_get(host, oid_errors)
    dis1 = await _snmp_get(host, oid_discards)
    pkt1 = await _snmp_get(host, oid_ucast)

    if any(v is None for v in (err1, dis1, pkt1)):
        return None

    await asyncio.sleep(interval_sec)

    # Второй снимок
    err2 = await _snmp_get(host, oid_errors)
    dis2 = await _snmp_get(host, oid_discards)
    pkt2 = await _snmp_get(host, oid_ucast)

    if any(v is None for v in (err2, dis2, pkt2)):
        return None

    bad = (err2 - err1) + (dis2 - dis1)   # плохие пакеты за интервал
    total = (pkt2 - pkt1) + bad            # всего пакетов за интервал

    if total == 0:
        return 0.0  # трафика не было — потерь нет

    return min(1.0, bad / total)


def normalize_loss(loss_ratio: float) -> float:
    """Нормировать потери в метрику m3 (0..1, где 1 = лучшее).

    Args:
        loss_ratio: Доля потерь 0..1 (0 = нет потерь, 1 = все потеряны).

    Returns:
        m3 = 1 - loss_ratio.
    """
    return 1.0 - loss_ratio

# OID состояния BFD-сессии
# 1 = adminDown, 2 = down, 3 = init, 4 = up
OID_BFD_SESS_STATE = "1.3.6.1.2.1.222.1.2.1.8"

BFD_STATE_UP = 4


class BfdMonitor:
    """Отслеживает состояние BFD-сессий и считает падения в скользящем окне.

    Args:
        host: IP-адрес роутера (R4).
        window_sec: Длина скользящего окна в секундах (по умолчанию 5 минут).
        max_flaps: Число падений при котором m4 = 0.
    """

    def __init__(
        self,
        host: str,
        window_sec: int = 300,
        max_flaps: int = 5,
    ) -> None:
        self.host = host
        self.window_sec = window_sec
        self.max_flaps = max_flaps

        # Храним timestamp каждого падения в скользящем окне
        self._flap_times: deque[float] = deque()

        # Последнее известное состояние каждой сессии {sess_index: state}
        self._last_states: dict[int, int] = {}

    async def poll(self) -> None:
        """Опросить состояние всех BFD-сессий и зафиксировать падения.

        Вызывается периодически из главного цикла.
        """
        states = await self._get_all_bfd_states()

        for sess_index, state in states.items():
            prev = self._last_states.get(sess_index)

            # Фиксируем падение если сессия перешла из Up в Down
            if prev == BFD_STATE_UP and state != BFD_STATE_UP:
                logger.info("BFD сессия %d упала (state=%d)", sess_index, state)
                self._flap_times.append(time.time())

            self._last_states[sess_index] = state

    def get_flap_count(self) -> int:
        """Подсчитать падения в скользящем окне.

        Устаревшие события (старше window_sec) удаляются.

        Returns:
            Число падений за последние window_sec секунд.
        """
        cutoff = time.time() - self.window_sec
        while self._flap_times and self._flap_times[0] < cutoff:
            self._flap_times.popleft()
        return len(self._flap_times)

    def get_m4(self) -> float:
        """Вычислить метрику m4 на основе текущей истории падений.

        Returns:
            m4 в диапазоне [0.0, 1.0]. 1.0 = нет падений, 0.0 = max_flaps и более.
        """
        flaps = self.get_flap_count()
        return max(0.0, 1.0 - flaps / self.max_flaps)

    async def _get_all_bfd_states(self) -> dict[int, int]:
        """Получить состояние всех BFD-сессий с роутера.

        Returns:
            Словарь {sess_index: state}.
        """
        try:
            client = puresnmp.PyWrapper(puresnmp.Client(self.host, puresnmp.V2C("public")))
            results = {}
            async for oid, value in client.walk(OID_BFD_SESS_STATE):
                # Последний элемент OID — индекс сессии
                sess_index = int(str(oid).split(".")[-1])
                results[sess_index] = int(value)
            return results
        except Exception as exc:
            logger.warning("BFD SNMP ошибка для %s: %s", self.host, exc)
            return {}

class SyslogListener:
    """Слушает UDP syslog на порту 514 и фиксирует BFD-события.

    Когда роутер шлёт сообщение о падении BFD-сессии —
    записываем timestamp в BfdMonitor.

    Args:
        bfd_monitor: Экземпляр BfdMonitor куда пишем события.
        host: IP на котором слушаем (по умолчанию все интерфейсы).
        port: UDP порт (по умолчанию 514).
    """

    # Ключевые слова в syslog которые говорят о падении BFD
    BFD_DOWN_KEYWORDS = [
        "BFD adjacency down",
        "BFD_SESS_DESTROYED",
        "BFD adjacency changed",
    ]

    def __init__(
        self,
        bfd_monitor: BfdMonitor,
        host: str = "0.0.0.0",
        port: int = 514,
    ) -> None:
        self.bfd_monitor = bfd_monitor
        self.host = host
        self.port = port
        self._server: Optional[socketserver.UDPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Запустить syslog-сервер в фоновом потоке."""
        listener = self  # передаём себя в handler через замыкание

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                data = self.request[0].decode(errors="ignore")
                listener._handle_message(data)

        self._server = socketserver.UDPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("SyslogListener запущен на %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Остановить syslog-сервер."""
        if self._server:
            self._server.shutdown()
            logger.info("SyslogListener остановлен")

    def _handle_message(self, message: str) -> None:
        """Обработать входящее syslog-сообщение.

        Args:
            message: Текст syslog-сообщения от роутера.
        """
        logger.debug("Syslog: %s", message.strip())

        for keyword in self.BFD_DOWN_KEYWORDS:
            if keyword in message:
                logger.info("BFD событие зафиксировано: %s", message.strip())
                self.bfd_monitor._flap_times.append(time.time())
                break


@dataclass
class RawMetrics:
    """Сырые измерения по каналу до нормировки.

    Все значения могут быть None если источник недоступен.
    """
    timestamp: float
    load_utilization: Optional[float]  # 0..1
    latency_ms: Optional[float]  # мс
    loss_ratio: Optional[float]  # 0..1
    m4: Optional[float]  # 0..1 уже нормированная


async def collect(
        host_r2: str,
        host_r4: str,
        if_index: int,
        max_bandwidth_bps: float,
        bfd_monitor: BfdMonitor,
) -> RawMetrics:
    """Собрать все метрики параллельно через asyncio.gather.

    m1, m2, m3 запускаются одновременно — сбор не блокируется
    из-за медленного источника. Если источник недоступен —
    возвращает None для этой метрики, не роняет всю систему.

    Args:
        host_r2: IP роутера для SNMP и ping.
        host_r4: IP роутера для BFD.
        if_index: Индекс интерфейса для SNMP.
        max_bandwidth_bps: Максимальная пропускная способность в бит/с.
        bfd_monitor: Экземпляр BfdMonitor для m4.

    Returns:
        RawMetrics с сырыми значениями и timestamp.
    """
    ts = time.time()

    # Запускаем m1, m2, m3 параллельно
    load, rtt, loss = await asyncio.gather(
        measure_load(host_r2, if_index=if_index, max_bandwidth_bps=max_bandwidth_bps),
        measure_latency(host_r2),
        measure_loss(host_r2, if_index=if_index),
        return_exceptions=False,
    )

    # m4 из BfdMonitor (синхронно — просто читаем память)
    m4 = bfd_monitor.get_m4()

    raw = RawMetrics(
        timestamp=ts,
        load_utilization=load,
        latency_ms=rtt,
        loss_ratio=loss,
        m4=m4,
    )

    # Логируем сырые измерения перед нормировкой
    logger.info(
        "Сырые метрики | timestamp=%.3f | load=%.4f | rtt=%.3f мс | loss=%.4f | m4=%.3f",
        raw.timestamp,
        raw.load_utilization if raw.load_utilization is not None else -1,
        raw.latency_ms if raw.latency_ms is not None else -1,
        raw.loss_ratio if raw.loss_ratio is not None else -1,
        raw.m4 if raw.m4 is not None else -1,
    )

    return raw