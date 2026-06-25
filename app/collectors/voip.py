from typing import Dict
from app.collectors.generic import Metric
from app.collectors.generic import Collector

class ChannelsCountMetric(Metric):
    name = "channels-count"
    description = (
        "Report the number of active channels and active calls currently "
        "handled by the Asterisk PBX."
    )
    shell = 'asterisk -rx "core show channels count"'

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "core show channels count"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ChannelsMetric(Metric):
    name = "channels"
    description = (
        "List the active PJSIP channels on the Asterisk PBX, showing the "
        "endpoints and the state of each ongoing call."
    )
    shell = 'asterisk -rx "pjsip show channels"'

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "pjsip show channels"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ChannelStatsMetric(Metric):
    name = "channelstats"
    description = (
        "Show per-channel RTP statistics for active PJSIP calls, including "
        "jitter, packet loss and round-trip time. Useful to diagnose audio "
        "quality issues."
    )
    shell = 'asterisk -rx "pjsip show channelstats"'

    def _mount_shell_command(self) -> str:
        return 'asterisk -rx "pjsip show channelstats"'

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ContactsMetric(Metric):
    name = "contacts"
    description = (
        "List the registered PJSIP contacts (AOR bindings) known to the "
        "Asterisk PBX. An optional PATTERN filters the output via grep."
    )
    shell = 'asterisk -rx "pjsip show contacts" [| grep PATTERN]'
    arguments_doc = "PATTERN (optional) — grep filter applied to the contact list, e.g. 2020@"

    def _mount_shell_command(self, grep_pattern: str = "") -> str:
        command = 'asterisk -rx "pjsip show contacts"'
        if grep_pattern:
            command += f" | grep {grep_pattern}"
        return command

    def mount_shell_command(self) -> str:
        # Optional: any argument is passed straight through to a grep filter,
        # e.g. voip-contacts 2020@  ->  asterisk -rx "pjsip show contacts" | grep 2020@
        return self._mount_shell_command(" ".join(self.arguments))

METRICS: list[type[Metric]] = [
    ChannelsCountMetric,
    ChannelsMetric,
    ChannelStatsMetric,
    ContactsMetric
]

class VoipCollector(Collector):
    base_name = "voip"
    description = "Asterisk PBX / VoIP metrics: channels and contacts."

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)
