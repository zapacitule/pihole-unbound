# PUA — Pi-hole + Unbound Auto-Deployer

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue)](https://python.org)
[![Version](https://img.shields.io/badge/Version-2.1.2-brightgreen)](CHANGELOG.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/zapacitule/pihole-unbound/pulls)

> **One command. Full privacy.** Deploy Pi-hole + Unbound on Debian/Ubuntu/Mint/Fedora (RPi OS experimental) in under 5 minutes with zero manual configuration.

```bash
python3 pua.py
```

---

## Why This Exists

**The problem:** Your ISP sees every DNS query you make. Google, Cloudflare, or your ISP collects your browsing history. Ads and trackers follow you everywhere.

**The solution:** Run your own recursive DNS server at home. Pi-hole blocks ads network-wide. Unbound queries root DNS servers directly — no middleman, no logging, no tracking.

**The catch:** Setting up Pi-hole + Unbound manually takes 20+ minutes of copying configs, editing files, and debugging.

**PUA fixes that.** One script. Five questions. Done.

---

## Features

* **Multi-OS support** — Debian 12+, Ubuntu 22.04+, Linux Mint 21+, Fedora, Raspberry Pi OS (experimental)
* **Auto-detect network** — interface, gateway, and current IP detected automatically
* **Static IP in 30 seconds** — interfaces / netplan YAML / nmcli (auto-selected per OS)
* **Pi-hole v6 on port 80** — admin panel accessible at `http://<ip>/admin` (no port suffix needed)
* **Unbound recursive** — true privacy, queries go directly to root DNS servers
* **Unbound DoT (TLS encrypted)** — ISP sees only "encrypted traffic to 9.9.9.9"
* **Custom DNS provider** — manually enter your own DoT server (any provider)
* **4 provider presets** — Quad9, Cloudflare, Google, or roll your own
* **Auto-connect Pi-hole ↔ Unbound** — upstream configured automatically
* **Install anywhere** — local (`--local`) or remote SSH, first menu asks which
* **Skip if installed** — detects existing Pi-hole/Unbound, skips re-installation
* **Force reinstall** — `--force` flag overrides skip and reinstalls from scratch
* **Progress bar** — live ASCII progress for every stage (`[████░░░] 65%`)
* **Verified commands** — every step is actually checked, not blindly assumed
* **Auto mode** — `--host --user --password` flags skip interactive prompts
* **19 automated tests** — legitimate sites, ad blocking, DNSSEC validation
* **Installation report** — detailed summary saved to your Desktop

---

## Quick Start

```bash
# Install the only dependency
pip3 install pexpect

# Run interactively — first asks local or remote SSH
python3 pua.py

# Run locally on this machine (prompts for sudo password)
python3 pua.py --local

# Remote mode — fully automated (no prompts)
python3 pua.py --host 192.0.2.1 --user <username> --password <password>

# Force reinstall everything (skip detection override)
python3 pua.py --host 192.0.2.1 --user <username> --password <password> --force

# Full example
python3 pua.py \
  --host 192.0.2.1 --user admin --password <password> --force
```

The script will ask:

| Step | Question |
|------|----------|
| 1 | Install locally or via SSH? |
| 2 | If SSH: server IP, username, password |
| 3 | Static IP or keep DHCP? (recommended: static) |
| 4 | DNS mode: recursive or DoT encrypted? |
| 5 | If DoT: Quad9 / Cloudflare / Google / Custom? |

Already installed? The script detects it and skips re-installation.
Use `--force` to reinstall everything from scratch.

Then it installs everything. You watch. It tests. It reports.

---

## Interactive Flow

```
$ python3 pua.py

============================================================
 Pi-hole + Unbound Auto-Deployer (PUA)
============================================================
  This script will install and configure Pi-hole + Unbound.
  Supports: Debian, Ubuntu, Mint, Fedora

  Installation mode:
  1. Install locally (this machine)
  2. Install via SSH (remote server)
  Choose [1-2]: 2

  ─── Connection Details ───
   Server IP: 192.0.2.1
   SSH user: <username>
   SSH password: ********
   Root password: ********

   Continue? (y/n): y

  [*] Connecting to <username>@192.0.2.1...
  [OK] Connected to 192.0.2.1
  [*] Detected: debian (apt/interfaces)
  [OK] Unbound OK (skip)
  [OK] Pi-hole OK (skip)
  [*] Interface: eth0, Gateway: 192.168.1.1

  ─── IP Configuration ───
   Static IP is RECOMMENDED for Pi-hole.
   1. Set static IP (recommended)
   2. Keep DHCP (skip)
   Choose [1-2]: 1
   Static IP [192.0.2.1]: 192.0.2.1
   Gateway [192.168.1.1]:

   [OK] Config written to /etc/network/interfaces
   [!] Restarting network... SSH will disconnect!
   [OK] Reconnected to 192.0.2.1

 ─── DNS Mode ───
   1. Recursive (direct root servers, ISP fragmented)
   2. DoT (TLS encrypted, ISP sees nothing)
   Choose [1-2]: 2

   Select DNS Provider:
   1. Quad9 (9.9.9.9@853)
   2. Cloudflare (1.1.1.1@853)
   3. Google (8.8.8.8@853)
   4. Custom (enter manually)
   Choose [1-4]: 1

   [... installation runs with progress bar ...]
   [██████████████████████████████░░░░░░]  80%  ✔ Connect Pi-hole ↔ Unbound
   [████████████████████████████████░░░░]  85%  ▶ DNS Tests

============================================================
 Running DNS Tests
============================================================
   [OK] google.com -> 142.250.140.139
   [OK] BLOCKED: doubleclick.net
   [OK] DNSSEC valid: dnssec.works -> 46.23.92.212
   [OK] DNSSEC invalid correctly: dnssec-failed.org

   Results:  Total=19  Passed=19  Failed=0

============================================================
 Installation Complete!
   Pi-hole admin:  http://192.0.2.1/admin
   DNS Server:     192.0.2.1
   Configure your router DHCP DNS to: 192.0.2.1
```

---

## DNS Modes

| Feature | Recursive | DoT (DNS-over-TLS) |
|---|---|---|
| **ISP visibility** | Sees individual queries (fragmented across 13+ servers) | Sees only "encrypted traffic to provider" |
| **Provider visibility** | Nobody — root servers don't log | Single provider sees all queries |
| **Encryption** | No (plain DNS on port 53) | Yes (TLS on port 853) |
| **DNSSEC** | ✅ Yes | ✅ Yes (provider verifies) |
| **Malware blocking** | ❌ No | ✅ Quad9 blocks known threats |
| **Trust model** | Trust root servers (ICANN, VeriSign, etc.) | Trust chosen provider |
| **Setup** | Default | Select provider from menu |

### Provider Presets (DoT mode)

| Provider | Addresses | Based in | Notable |
|---|---|---|---|
| **Quad9** | `9.9.9.9@853`, `149.112.112.112@853` | Zurich, CH | Non-profit, blocks malware |
| **Cloudflare** | `1.1.1.1@853`, `1.0.0.1@853` | USA | Fastest, WARP ecosystem |
| **Google** | `8.8.8.8@853`, `8.8.4.4@853` | USA | Reliable, data collection |
| **Custom** | Your own | Any | Any DoT-capable server |

---

## Supported Operating Systems

| OS | Package Manager | Network Configuration | Status |
|---|---|---|---|---|
| Debian 12 | `apt` | `/etc/network/interfaces` | ✅ Tested |
| Ubuntu 22.04 / 24.04 | `apt` | `/etc/netplan/*.yaml` | ✅ Should work |
| Linux Mint 21 / 22 | `apt` | `nmcli` (NetworkManager) | ✅ Should work |
| Fedora | `dnf` | `nmcli` (NetworkManager) | ⚠️ Untested (code ready) |
| Raspberry Pi OS | `apt` | `/etc/network/interfaces` | ⚠️ Experimental |

---

## Architecture

```
Pi-hole ←──── Unbound ←────── Root DNS (:53)     [RECURSIVE]
  :53            :5335           (:53)
  │                              │
  │                              └── Provider (:853) [DoT TLS]
  │
  └── Blocklists (ads + trackers)

  RECURSIVE:  Device ──→ Pi-hole (:53) ──→ Unbound (:5335) ──→ Root servers
  DoT:        Device ──→ Pi-hole (:53) ──→ Unbound (:5335) ──→ Provider (TLS)

Pipeline install order:
  1. Unbound     (downstream DNS — must be ready first)
  2. Pi-hole     (upstream DNS → points to Unbound)
  3. Connect     (wires Unbound as Pi-hole upstream)
  4. DNS Tests   (19 automated checks)
```

---

## Requirements

| Component | Minimum |
|---|---|
| **Target server** | Debian 12+, Ubuntu 22.04+, Mint 21+, Fedora, Pi OS (experimental) |
| **Python** | 3.8+ with `pexpect` |
| **SSH** | Enabled on target server |
| **RAM** | 512 MB |
| **CPU** | 1 core |
| **Disk** | 8 GB |

---

## Troubleshooting

### "Permission denied" on SSH
* Verify SSH is enabled: `systemctl status sshd`
* Check firewall: `ufw allow 22`

### "Command not found: curl"
* Run `apt install curl -y` on the target server first
* Or let the script handle it — it installs dependencies automatically

### Pi-hole installer fails
* Pi-hole uses `--unattended` mode — no dialogs involved
* Check `/etc/pihole/setupVars.conf` was created before the installer ran
* Ensure internet access: `ping google.com` from the target server

### Unbound fails to start
* Check: `systemctl status unbound`
* Common fix: port conflict with systemd-resolved (Pi-hole installer handles this automatically)
* Manual fix: `systemctl stop systemd-resolved && systemctl disable systemd-resolved`

### DNS works but ads aren't blocked
* Ensure router DHCP DNS points to Pi-hole: `192.0.2.1`
* Renew DHCP lease on client devices (reconnect WiFi / `ipconfig /renew`)
* Check Pi-hole dashboard: `http://192.0.2.1/admin`

### Pi-hole admin on port 80 (not 8080/8443)
* PUA configures Pi-hole v6 web interface on standard HTTP port 80 via `setcap cap_net_bind_service=+ep /usr/bin/pihole-FTL`
* Admin panel at `http://<ip>/admin` — no `:8080` or `:8443` suffix needed
* If you see "page not found" on port 80 after install, run: `sudo setcap cap_net_bind_service=+ep $(which pihole-FTL) && sudo systemctl restart pihole-FTL`

### Static IP change lost SSH connection
* The script reconnects automatically after 5 seconds
* If it fails, use VM console or physical keyboard to check `ip a`
* Verify `/etc/network/interfaces` (Debian) or `/etc/netplan/*.yaml` (Ubuntu)

### Already installed components
* PUA detects existing Pi-hole/Unbound and skips re-installation
* To force reinstall everything: `python3 pua.py --force`
* Script creates `/tmp/pua_force` marker — remove it to undo force mode

---

## Testing

After deployment, the script runs 19 automated checks:

```
Legitimate websites (10):   google.com, facebook.com, youtube.com,
                            github.com, wikipedia.org, reddit.com,
                            amazon.com, stackoverflow.com, twitter.com, linkedin.com

Ad/Tracker blocking (6):    doubleclick.net, googlesyndication.com,
                            ads.google.com, pagead2.googlesyndication.com,
                            adservice.google.com, analytics.google.com

DNSSEC validation (2):      dnssec.works (valid), dnssec-failed.org (invalid)

Service verification (1):   pihole-FTL active check
```

All results saved to `~/Desktop/pihole-report-TIMESTAMP.txt`

---

## Contributing

Found a bug? Want to add support for a new OS?

1. Fork the repo
2. Create a branch: `git checkout -b feature/os-name`
3. Code your changes
4. Test on a VM: `python3 pua.py`
5. Submit a PR

See [ROADMAP.md](ROADMAP.md) for planned features.

---

## Support

If PUA saved you time, consider supporting the project:

[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-red?logo=github)](https://github.com/sponsors/zapacitule)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-%E2%98%95-yellow)](https://buymeacoffee.com/zapacitule)

---

## License

MIT — see [LICENSE](LICENSE)

---

**Made with ☕ and frustration at ISP DNS snooping.**
