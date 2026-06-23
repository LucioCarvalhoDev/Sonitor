from typing import Dict
from app.collectors.generic import Metric
from app.collectors.generic import Collector

class ChannelsCountMetric(Metric):
    name = "channels-count"

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "core show channels count"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ChannelsMetric(Metric):
    name = "channels"

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "pjsip show channels"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ChannelStatsMetric(Metric):
    name = "channelstats"

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "pjsip show channelstats"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ContactsMetric(Metric):
    name = "contacts"

    def _mount_shell_command(self, grep_pattern: str = "") -> str:
        command = 'asterisk -rx "pjsip show contacts"'
        if grep_pattern:
            command += f" | grep {grep_pattern}"
        return command

    def mount_shell_command(self) -> str:
        # Optional: any argument is passed straight through to a grep filter,
        # e.g. voip-contacts 2020@  ->  asterisk -rx "pjsip show contacts" | grep 2020@
        return self._mount_shell_command(" ".join(self.arguments))

class SipMetric(Metric):
    name = "sip"

    def _mount_shell_command(self, sngrep_arguments: str) -> str:
        return f"sngrep {sngrep_arguments}"

    def mount_shell_command(self) -> str:
        if not self.arguments:
            raise ValueError(
                'metric \'voip-sip\' requires sngrep arguments, '
                'e.g. voip-sip "-N -q -O /tmp/capture.pcap"'
            )
        return self._mount_shell_command(" ".join(self.arguments))


METRICS: list[type[Metric]] = [
    ChannelsCountMetric,
    ChannelsMetric,
    ChannelStatsMetric,
    SipMetric,
    ContactsMetric
]

class VoipCollector(Collector):
    base_name = "voip"

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)
