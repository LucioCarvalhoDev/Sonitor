from app.collectors.generic import Metric, MetricResult, Collector
from app.collectors.net import PingMetric, DnsMetric, PublicIPMetric, NetCollector
from app.collectors.sys import SystemCollector, StorageMetric, UptimeMetric, TopMetric
import re


COLLECTORS = [
    NetCollector,
    SystemCollector
]

__all__ = [
    "Metric",
    "MetricResult",
    "PingMetric",
    "DnsMetric",
    "PublicIPMetric",
    "StorageMetric",
    "UptimeMetric"
] + COLLECTORS



class CollectorRepository():
    collectors = {
        f"{collector.base_name}": collector for collector in COLLECTORS
    }

    @classmethod
    def resolve_collector(cls, name: str) -> Collector:
        found = None
        for collector_name, collector in cls.collectors.items():
            if name != collector_name:
                continue
            found = collector
        
        if found is None:
            raise ValueError(f"Not found collector of name '{name}'.")
        
        return found
    
    @classmethod
    def resolve(cls, fullname: str) -> type[Metric]:
        collector_name, metric_name = fullname.split('-', 1)

        collector = cls.resolve_collector(collector_name)
        metric = collector.get_metric(fullname)
        return metric

