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