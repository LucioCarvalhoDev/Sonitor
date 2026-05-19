from app.collectors import Metric, MetricResult, PingMetric, DnsMetric, NetCollector, SystemCollector, StorageMetric, UptimeMetric, CollectorRepository
from app.execution.shell_executor import ShellExecutor

address = "clivale.linepbx.com.br"
net = NetCollector()

dns = DnsMetric(address)
df = StorageMetric()
up = UptimeMetric()

arg = "net-ping"


# print(ShellExecutor.collect(dns).as_prompt())
# print(ShellExecutor.collect(up).as_prompt())

# CollectorRepository.parse_to_prompt("net-dns clivale.linepbx.com.br")
# print()

# print(ShellExecutor.collect(CollectorRepository.resolve(arg)(address)).as_prompt())

class Sonitor():

    def parse_metrics(self, expression: str):
        metric_expressions = expression.strip().split('--metric')

        metrics: list[type[Metric]] = []

        for expression in metric_expressions:
            expression = expression.strip()
            if expression == '':
                continue

            components = expression.split(' ', 1)
            name = components.pop(0)
            arguments = components

            metric = CollectorRepository.resolve(name)(arguments)

            metrics.append(metric)

        return metrics
    
    def run(self, expression: str) -> str:
        metrics: list[type[Metric]] = self.parse_metrics(expression)
        results: list[str] = []

        for metric in metrics:
            metric_result: MetricResult = ShellExecutor.collect(metric)

            results.append(metric_result.as_prompt())
        
        return '\n'.join(results)
    


app = Sonitor()

exp = "--metric sys-storage --metric sys-top --metric net-ping clivale.linepbx.com.br"

# app.parse_metrics()
print(app.run(exp))