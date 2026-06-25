import asyncio
import re
import logging

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