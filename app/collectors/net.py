from typing import Dict, Any
from app.collectors.generic import Metric
from app.collectors.generic import Collector

class PingMetric(Metric):
    name = "ping"

    def _mount_shell_command(self, address: str) -> str:
        return f"ping {address} -c 4"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command(self.arguments[0])

class DnsMetric(Metric):
    name = "dns"

    def _mount_shell_command(self, address: str) -> str:
        return f"nslookup {address}"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command(self.arguments[0])

class PublicIPMetric(Metric):
    name = "public-ip"
    
    def _mount_shell_command(self, address: str) -> str:
        return f"curl -4 -s ifconfig.me"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command(self.arguments[0])


METRICS: list[type[Metric]] = [DnsMetric, PingMetric, PublicIPMetric]

class NetCollector(Collector):
    base_name = "net"

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)



