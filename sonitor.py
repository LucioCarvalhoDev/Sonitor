from app.collectors.net import PingMetric, DnsMetric, NetCollector

address = "clivale.linepbx.com.br"
net = NetCollector()
# dns = DnsMetric(address)
# ping = PingMetric(address)
# print(ping.run(), dns.run())

print(net._parse("net-public-ip").collect().as_prompt())