# Changelog

All notable changes to this project will be documented in this file.

---

## [2.1.3] - 2026-06-16

### Fixed
- **Intermittent NTP sync failure** — Pi-hole FTL NTP client would occasionally warn "No valid NTP replies received" when `pool.ntp.org` returned a temporarily unreachable server. Since FTL only uses a single NTP server, any transient failure would cause a sync cycle to fail.
  - **Fix**: Configured 3 NTP fallback servers: `pool.ntp.org`, `time.cloudflare.com`, `time.google.com`. FTL will try each in order until one responds, eliminating single-point-of-failure NTP sync interruptions.
  - Applied at install time (pua.py `connect_pihole_unbound()`) and on existing installs via `sed`.

---

## [2.1.2] - 2026-06-09

### Fixed

### Fixed
- **TCP "Connection prematurely closed by remote server"** — root cause identified and resolved:
  - **Kernel socket buffer limit**: Unbound config sets `so-rcvbuf: 1m`, but Debian defaults `net.core.rmem_max=212992` (5× too small). Kernel silently capped the buffer, causing TCP failures on large DNSSEC responses. Now set to `5242880` (5MB) and persisted in `/etc/sysctl.conf`.
  - **Unbound systemd `$DAEMON_OPTS`**: `ExecStart=/usr/sbin/unbound -d -p $DAEMON_OPTS` referenced an unset variable (`/etc/default/unbound` missing). Created systemd override at `/etc/systemd/system/unbound.service.d/override.conf` with direct `ExecStart=/usr/sbin/unbound -d -p`.
- **`incoming-num-tcp`**: increased from 100→200 for burst tolerance.
- Applied to both machines at install time (pua.py `install_unbound()`).

---

## [2.1.1] - 2026-06-06

### Fixed
- **TCP connection prematurely closed** — increased `incoming-num-tcp` from 30→100, `tcp-idle-timeout` from 120→300, `num-threads` from 1→2 to handle burst DNS queries without dropping TCP connections to Pi-hole FTL

---

## [2.1.0] - 2026-06-03

### Fixed
- `ver_active` now checks exact `"active"` string — no more false positives on "activating"/"deactivating"
- RPi OS detection via `VARIANT_ID=raspbian` — uses `sudo -i` instead of crashing on `su -`
- OS-aware Unbound paths: `root_key_src`, `unbound_key_dir`, `unbound_conf_d`, `unbound_user` in `_classify_os()`
- Fedora root key: uses `/etc/unbound/root.key` instead of Debian's `/usr/share/dns/root.key`
- `write_file()` no longer shadows global `ok()` function
- `LocalSession.cmd()` no longer appends stderr to stdout (false positives in verifiers)
- `save_report()` admin URL now includes port number
- `_detect_os()` increased timeout from 10s to 15s for slower systems

### Changed
- **Interactive menu restructured**: first question is now "Install locally or via SSH?" instead of jumping directly to SSH details
- Title banner updated: "Raspberry Pi OS (experimental)", Alpine removed
- `_detect_os()` now parses VARIANT_ID and VARIANT fields for RPi OS detection

### Added
- Unbound-related OS fields in `_classify_os()`: `unbound_user`, `root_key_src`, `unbound_key_dir`, `unbound_conf_d`
- Conditional root key provisioning: skips `cp` if `root_key_src` is empty (Alpine fallback)
- Pi-hole web interface configured on port 80 (instead of default 8080/8443)
  - Sets `cap_net_bind_service` on pihole-FTL binary to allow binding to port 80 as non-root
  - Updates `pihole.toml` webserver port to `80o,443os`
  - Applied both on fresh install and existing installs (in `connect_pihole_unbound`)
- `--force` flag to reinstall even if already installed
- Pre-installation checks: skip Unbound/Pi-hole if already installed/running

---

## [2.0.0] - 2026-06-03

### Added
- ASCII progress bar (`[████░░░░░] 55%`) for all installation stages
- Pipeline system with weighted stage progression
- `vcmd()` — verified command execution (real result checking, not blind sleep)
- Real verification for ALL commands using verifiers:
  - `ver_active` — checks systemctl active status
  - `ver_contains` — checks output contains substring
  - `ver_which` — checks binary exists
  - `ver_not_empty` — checks non-empty output
- Pi-hole password set during installation step (not after)
- `write_file()` — base64-encoded file writes (avoids heredoc SSH bug)
- `_classify_os()` — shared OS classification (eliminates ~30 lines duplication)
- Auto mode — `--host --user --password --root-password` skips all prompts
- DNSSEC invalid test: replaced `fail01.dnssec.works` with `dnssec-failed.org`

### Changed
- **Pi-hole installation**: replaced fragile `pexpect` dialog navigation (8 dialogs) with `--unattended` mode
  - Pre-creates `/etc/pihole/setupVars.conf` before running installer
  - Skips all ncurses dialogs — no version/locale dependency
  - Verifies installation with `which pihole` + `systemctl is-active pihole-FTL`
  - Verifies DNS resolution after install
- **Network restart**: removed invalid `nmcli_managed` string; handles each method directly
- **Report generation**: verifies actual install state (not assumed) before writing report
- **Dependencies**: added `wget` and `git` to dependency install list

### Architecture
- `ProgressBar` class — ASCII progress display on local terminal
- `Pipeline` class — runs stages sequentially with weighted progress
- Pipeline stops on first failure instead of continuing blind
- Each stage reports sub-progress via callback

---

## [1.0.0] - 2026-06-03

### Added
- Initial release
- OS detection: Debian 12, Ubuntu 22.04+, Linux Mint 21+, Fedora, Raspberry Pi OS
- Auto-detect network interface, gateway, and current IP
- Static IP configuration via 3 methods:
  - `/etc/network/interfaces` (Debian, Pi OS)
  - `netplan` YAML (Ubuntu)
  - `nmcli` (Mint, Fedora)
- Pi-hole v6 installation with automated `dialog` (ncurses) navigation
- Unbound installation with two modes:
  - Recursive (direct root servers, no ISP)
  - DoT encrypted (TLS, ISP can't see queries)
- DoT provider selection: Quad9, Cloudflare, Google, Custom
- Automatic Pi-hole ↔ Unbound connection via `pihole.toml`
- 18+ automated DNS tests (websites, ads, DNSSEC)
- Installation report saved to Desktop
- Full privilege detection: `sudo` vs `su -c`
- Color output (green/red/yellow)
