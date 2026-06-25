from typing import Dict, Any
from app.collectors.generic import Metric
from app.collectors.generic import Collector

class PingMetric(Metric):
    name = "ping"
    description = (
        "Send 4 ICMP echo requests to ADDRESS and report latency and packet "
        "loss. Useful to check reachability and link quality to a host."
    )
    shell = "ping ADDRESS -c 4"
    arguments_doc = "ADDRESS (required) — hostname or IP to ping, e.g. 8.8.8.8"

    def _mount_shell_command(self, address: str) -> str:
        return f"ping {address} -c 4"

    def mount_shell_command(self) -> str:
        if not self.arguments:
            raise ValueError("metric 'net-ping' requires an address argument, e.g. net-ping 8.8.8.8")
        return self._mount_shell_command(self.arguments[0])

class DnsMetric(Metric):
    name = "dns"
    description = (
        "Resolve ADDRESS through the host's configured DNS servers and print "
        "the resulting records. Useful to confirm name resolution is working."
    )
    shell = "nslookup ADDRESS"
    arguments_doc = "ADDRESS (required) — hostname to resolve, e.g. google.com"

    def _mount_shell_command(self, address: str) -> str:
        return f"nslookup {address}"

    def mount_shell_command(self) -> str:
        if not self.arguments:
            raise ValueError("metric 'net-dns' requires an address argument, e.g. net-dns google.com")
        return self._mount_shell_command(self.arguments[0])

class PublicIPMetric(Metric):
    name = "public-ip"
    description = (
        "Discover the host's public IPv4 address as seen from the internet by "
        "querying the external echo service ifconfig.me."
    )
    shell = "curl -4 -s ifconfig.me"

    def _mount_shell_command(self) -> str:
        return f"curl -4 -s ifconfig.me"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()


METRICS: list[type[Metric]] = [DnsMetric, PingMetric, PublicIPMetric]

class NetCollector(Collector):
    base_name = "net"
    description = "Network reachability and connectivity metrics."

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)



