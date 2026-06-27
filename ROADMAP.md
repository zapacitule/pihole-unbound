# ROADMAP - PUA (Pi-hole + Unbound Auto-Deployer)

## v1.0 - Initial Release

- ✅ OS Detection: Debian, Ubuntu, Mint, Fedora, Raspberry Pi OS
- ✅ Auto-detect network interface + gateway
- ✅ Static IP configuration (interfaces / netplan / nmcli)
- ✅ Pi-hole v6 installation (automated dialog navigation)
- ✅ Unbound installation + configuration
- ✅ DNS mode selection: Recursive or DoT (encrypted)
- ✅ DoT provider selection: Quad9, Cloudflare, Google, Custom
- ✅ Automatic Pi-hole ↔ Unbound connection
- ✅ 18+ automated DNS tests
- ✅ Installation report on Desktop

---

## v2.0 - Stable Automation (Current)

- ✅ Unattended Pi-hole install (no ncurses dialogs)
- ✅ ASCII progress bar with Pipeline system
- ✅ Verified commands (`vcmd()`) — every step checked
- ✅ Local mode (`--local` flag)
- ✅ Auto mode — `--host --user --password --root-password`
- ✅ `write_file()` — base64 file writes (no heredoc bugs)
- ✅ `_classify_os()` — deduplicated OS classification
- ✅ Fixed DNSSEC test (`dnssec-failed.org`)
- ✅ 19/19 automated DNS tests

---

## v2.1 - Multi-OS Polish

- ✅ `ver_active` exact match (no more "activating"/"deactivating" false positives)
- ✅ OS-aware Unbound paths via `_classify_os()` (root_key_src, unbound_user, conf_d)
- ✅ RPi OS detection via VARIANT_ID + `sudo -i` instead of `su -`
- ✅ Fedora root key path (`/etc/unbound/root.key`)
- ✅ Interactive menu: local or remote SSH first question
- ✅ `write_file()` no longer shadows global `ok()`
- ✅ `save_report()` includes admin port in URL
- ✅ Pi-hole v6 admin on port 80 via `setcap cap_net_bind_service=+ep`
- ✅ Pre-installation detection: skip Unbound/Pi-hole if already installed
- ✅ `--force` flag to override skip and reinstall from scratch
- ✅ **TCP "Connection prematurely closed" fix** — kernel socket buffers (`rmem_max=5242880`) + systemd override (no `$DAEMON_OPTS`) + `incoming-num-tcp=200` + TCP SYN backlog (`net.ipv4.tcp_max_syn_backlog=1024`)

- ✅ **Reconfiguration menu** — detect existing install, offer port/password/upstream/DNS mode changes without reinstalling
- ✅ **DoT toggle** — switch Unbound recursive ↔ DoT from reconfigure menu
- [ ] Alpine Linux support (apk + rc-service) — *needs OpenRC rewrite*
- [ ] Resume after failure (save progress)
- [ ] Color output toggle (--no-color flag)
- [ ] Log file for debugging (-v / --verbose flag)
- [ ] Pre-flight checks (internet connectivity, disk space, port conflicts)

---

## v2.2 - Nice-to-Have

- [ ] Preset configurations (save/load config)
- [ ] Custom blocklists during install
- [ ] Docker installation mode (alternative to bare metal)

---

## v3.0 - Quality of Life

- [ ] Backup/restore configuration

---

## v4.0 - Protocol & Infrastructure

- [ ] DoH (DNS over HTTPS) support in addition to DoT
- [ ] IPv6 full support
- [ ] Terraform/Ansible provider
- [ ] Keepalived / VRRP cluster — Virtual IP failover între 2+ Pi-hole-uri
- [ ] Orbital Sync — sincronizare config/whitelist/blocklist între noduri
- [ ] DNSdist — load balancing între multiple Pi-hole-uri
