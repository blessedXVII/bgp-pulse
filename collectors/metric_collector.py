import asyncio
import re
import logging
import puresnmp

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
