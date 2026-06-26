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

class IPMetric(Metric):
    name = "ip"
    description = (
        "Show the host's network interfaces and their IP addresses in a brief, "
        "columnar form (one line per interface)."
    )
    shell = "ip -brief address"

    def _mount_shell_command(self) -> str:
        return f"ip -brief address"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ConnectionsMetric(Metric):
    name = "connections"
    description = (
        "Summarize socket statistics and list the active TCP and UDP "
        "connections (with owning processes). Useful to see what the host is "
        "talking to."
    )
    shell = "ss -s; ss -tunp"

    def _mount_shell_command(self) -> str:
        return f"ss -s; ss -tunp"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ListeningMetric(Metric):
    name = "listening"
    description = (
        "List the TCP ports the host is listening on, with the owning "
        "processes. Useful to audit exposed services."
    )
    shell = "ss -tlnp"

    def _mount_shell_command(self) -> str:
        return f"ss -tlnp"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class RouteMetric(Metric):
    name = "route"
    description = (
        "Print the host's IP routing table, including the default gateway. "
        "Useful to confirm traffic is routed as expected."
    )
    shell = "ip route"

    def _mount_shell_command(self) -> str:
        return f"ip route"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class HttpMetric(Metric):
    name = "http"
    description = (
        "Probe URL with curl and report the HTTP status code and connection "
        "and total timings. Useful to check an endpoint is up and responsive."
    )
    shell = 'curl -s -o /dev/null -w "http_code=... time_total=...s" URL'
    arguments_doc = "URL (required) — endpoint to probe, e.g. https://example.com"

    def _mount_shell_command(self, url: str) -> str:
        return (
            'curl -s -o /dev/null -w '
            '"http_code=%{http_code} time_connect=%{time_connect}s time_total=%{time_total}s\\n" '
            f"{url}"
        )

    def mount_shell_command(self) -> str:
        if not self.arguments:
            raise ValueError("metric 'net-http' requires a URL argument, e.g. net-http https://example.com")
        return self._mount_shell_command(self.arguments[0])


METRICS: list[type[Metric]] = [
    DnsMetric,
    PingMetric,
    PublicIPMetric,
    IPMetric,
    ConnectionsMetric,
    ListeningMetric,
    RouteMetric,
    HttpMetric,
]

class NetCollector(Collector):
    base_name = "net"
    description = "Network reachability, connectivity and socket metrics."

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)



