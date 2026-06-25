import pytest
from collectors.metric_collector import (
    _parse_rtt, normalize_latency, normalize_load
)
from unittest.mock import AsyncMock, patch

class TestParseRtt:
    """Тесты парсинга вывода ping."""

    PING_OK = (
        "PING 10.0.42.1 56(84) bytes of data.\n"
        "64 bytes from 10.0.42.1: icmp_seq=1 ttl=255 time=1.23 ms\n"
        "--- 10.0.42.1 ping statistics ---\n"
        "10 packets transmitted, 10 received, 0% packet loss\n"
        "rtt min/avg/max/mdev = 1.100/1.230/1.500/0.080 ms\n"
    )

    PING_LOSS = (
        "10 packets transmitted, 8 received, 20% packet loss\n"
        "rtt min/avg/max/mdev = 1.100/1.230/1.500/0.080 ms\n"
    )

    def test_parse_нормальный_вывод(self):
        assert _parse_rtt(self.PING_OK) == pytest.approx(1.230)

    def test_parse_вывод_с_потерями(self):
        """Потери пакетов не мешают парсингу RTT."""
        assert _parse_rtt(self.PING_LOSS) == pytest.approx(1.230)

    def test_parse_мусорный_вывод(self):
        """Нечитаемый вывод возвращает None, не бросает исключение."""
        assert _parse_rtt("garbage") is None


class TestNormalizeLatency:
    """Тесты нормировки RTT → m2."""

    def test_ноль_мс(self):
        assert normalize_latency(0.0) == pytest.approx(1.0)

    def test_максимум(self):
        assert normalize_latency(200.0) == pytest.approx(0.0)

    def test_половина(self):
        assert normalize_latency(100.0) == pytest.approx(0.5)

    def test_превышение_максимума_зажато_в_ноль(self):
        """RTT больше max_rtt_ms не уходит в минус."""
        assert normalize_latency(500.0) == pytest.approx(0.0)

    def test_кастомный_максимум(self):
        assert normalize_latency(50.0, max_rtt_ms=100.0) == pytest.approx(0.5)

class TestNormalizeLoad:
    """Тесты нормировки утилизации → m1."""

    def test_пустой_канал(self):
        assert normalize_load(0.0) == pytest.approx(1.0)

    def test_полный_канал(self):
        assert normalize_load(1.0) == pytest.approx(0.0)

    def test_половина(self):
        assert normalize_load(0.5) == pytest.approx(0.5)


class TestMeasureLoad:
    """Тесты measure_load с моком SNMP."""

    @pytest.mark.asyncio
    async def test_нормальный_сбор(self):
        """Два снимка с разницей → корректная утилизация."""
        # Имитируем два снимка: входящие выросли на 125000 байт,
        # исходящие на 125000 байт за 1 секунду.
        # Итого: (125000 + 125000) * 8 / 1 = 2_000_000 бит/с
        # При max 10_000_000 бит/с → утилизация 0.2 → m1 = 0.8
        snmp_values = [
            1_000_000,   # in1
            1_000_000,   # out1
            1_125_000,   # in2
            1_125_000,   # out2
        ]

        with patch(
            "collectors.metric_collector._snmp_get",
            new_callable=AsyncMock,
            side_effect=snmp_values,
        ):
            from collectors.metric_collector import measure_load
            result = await measure_load(
                host="10.0.42.1",
                if_index=1,
                max_bandwidth_bps=10_000_000,
                interval_sec=1.0,
            )

        assert result == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_snmp_недоступен(self):
        """Если SNMP не отвечает → возвращаем None."""
        with patch(
            "collectors.metric_collector._snmp_get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from collectors.metric_collector import measure_load
            result = await measure_load(
                host="10.0.42.1",
                if_index=1,
                max_bandwidth_bps=10_000_000,
            )

        assert result is None