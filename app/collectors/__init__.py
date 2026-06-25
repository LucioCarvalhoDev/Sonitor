from app.collectors.generic import Metric, MetricResult, Collector, Snapshot
from app.collectors.net import PingMetric, DnsMetric, PublicIPMetric, NetCollector
from app.collectors.sys import SystemCollector, StorageMetric, UptimeMetric, TopMetric
from app.collectors.voip import (
    VoipCollector,
    ChannelsCountMetric,
    ChannelsMetric,
    ChannelStatsMetric,
)
import re


COLLECTORS = [
    NetCollector,
    SystemCollector,
    VoipCollector,
]

__all__ = [
    "Metric",
    "MetricResult",
    "Snapshot",
    "CollectorRepository",
    "PingMetric",
    "DnsMetric",
    "PublicIPMetric",
    "StorageMetric",
    "UptimeMetric",
    "ChannelsCountMetric",
    "ChannelsMetric",
    "ChannelStatsMetric",
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
        collector_name = cls.parse_collector_name(fullname)

        collector = cls.resolve_collector(collector_name)
        metric = collector.get_metric(fullname)
        return metric
    
    @staticmethod
    def parse_collector_name(fullname: str) -> str:
        return fullname.split('-', 1)[0]

    @classmethod
    def generate_man(cls, name: str) -> str:
        """Build the man page for ``name``, be it a collector or a metric.

        A bare collector base name (e.g. ``voip``) yields the collector man
        (its own description plus a line per metric); anything else is treated
        as a metric full name (e.g. ``voip-contacts``).
        """
        if name in cls.collectors:
            return cls.generate_collector_man(name)
        return cls.generate_metric_man(name)

    @classmethod
    def generate_collector_man(cls, name: str) -> str:
        """Build a collector's man page: its description plus its metric list.

        Resolution errors (unknown collector) propagate as ``ValueError``.
        """
        collector = cls.resolve_collector(name)

        description = collector.description or "No description available for this collector."

        lines = [
            name,
            "",
            description,
            "",
            "Metrics:",
        ]

        width = max((len(fullname) for fullname in collector.metrics), default=0)
        for fullname, metric_cls in collector.metrics.items():
            metric_description = metric_cls.description or "No description available for this metric."
            lines.append(f"  {fullname:<{width}}  {metric_description}")

        return "\n".join(lines)

    @classmethod
    def generate_metric_man(cls, fullname: str) -> str:
        """Build a metric's man page procedurally from its documentation fields.

        Reads the ``description``/``shell``/``arguments_doc`` class attributes
        of the resolved metric, falling back to placeholders when a field is
        not set. Resolution errors (unknown metric) propagate as ``ValueError``.
        """
        metric_cls = cls.resolve(fullname)

        description = metric_cls.description or "No description available for this metric."
        shell = metric_cls.shell or "No example available for this metric."
        arguments = metric_cls.arguments_doc or "None"

        lines = [
            fullname,
            "",
            description,
            "",
            f"Shell: {shell}",
            f"Arguments: {arguments}",
        ]
        return "\n".join(lines)
