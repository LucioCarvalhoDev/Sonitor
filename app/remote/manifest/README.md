# @@USER@@

This unprivileged `@@USER@@` user was created by **Sonitor**, an agentless
monitoring tool. It is reachable over SSH only with the key(s) listed in
`hosts.toml`, the account is password-locked (`passwd -l`), and it merely runs
read-only metric commands (uptime, df, asterisk) on demand. It runs no
daemon and opens no ports of its own.

Files in this directory:

  - version.toml   which provisioning version configured this host
  - hosts.toml     operator machines (by SSH key fingerprint) allowed to collect
  - uninstall.sh   remove this user and revert all changes, completely
  - README.md      this file

To remove @@USER@@ entirely, run as root on this host:

  sudo sh /home/@@USER@@/uninstall.sh

This deletes the user and its home directory, completely.
