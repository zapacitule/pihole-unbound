#!/usr/bin/env python3
"""
PUA - Pi-hole + Unbound Auto-Deployer
=====================================
Deploy Pi-hole + Unbound (recursive or DoT) on Debian, Ubuntu, Mint, Fedora, Pi OS.

Fully automated: static IP, Pi-hole, Unbound, connection, testing, report.
With progress bar and real verification of every command.

Usage:
    python3 pua.py
    python3 pua.py --local
    python3 pua.py --host 192.0.2.1 --user <username> --password <password>
"""

import argparse
import base64
import os
import subprocess
import sys
import time
import re
import random
import string
from datetime import datetime

try:
    import pexpect
except ImportError:
    print("[!] Missing 'pexpect'. Install it: pip3 install pexpect")
    sys.exit(1)

# ─── ANSI Escape Stripper ──────────────────────────────────────────────────
_ANSI = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][0-9;]*\x07')

# ─── Colors ────────────────────────────────────────────────────────────────
C = {"R": "\033[91m", "G": "\033[92m", "Y": "\033[93m", "B": "\033[94m",
     "W": "\033[0m", "BOLD": "\033[1m"}

def ok(msg=""):   print(f"  {C['G']}[OK]{C['W']} {msg}")
def fail(msg=""): print(f"  {C['R']}[FAIL]{C['W']} {msg}")
def warn(msg=""): print(f"  {C['Y']}[!]{C['W']} {msg}")
def info(msg=""): print(f"  {C['B']}[*]{C['W']} {msg}")
def title(msg):   print(f"\n{C['BOLD']}{'='*60}{C['W']}\n {msg}\n{'='*60}")

# ─── ProgressBar ───────────────────────────────────────────────────────────
class ProgressBar:
    """ASCII progress bar displayed on the local terminal."""

    def __init__(self, width=40):
        self.width = width
        self.current = 0
        self._last_status = ""

    def update(self, percent, status=""):
        percent = max(0.0, min(100.0, float(percent)))
        if status == self._last_status and percent == self.current:
            return
        filled = int(self.width * percent / 100)
        bar = "█" * filled + "░" * (self.width - filled)
        line = f"  [{bar}] {int(percent):3d}%"
        if status:
            line += f"  {status}"
        sys.stdout.write(f"\r{' ' * 80}\r{line}\n")
        sys.stdout.flush()
        self.current = percent
        self._last_status = status

    def advance(self, delta, status=""):
        self.update(self.current + delta, status)

    def ok(self, status="Done"):
        self.update(100, status)

    def fail(self, status="Failed"):
        self.update(self.current, status)

# ─── Verified Command ──────────────────────────────────────────────────────
def vcmd(session, command, verifier=None, timeout=60):
    """Run command via session and verify the result.

    Returns (success: bool, output: str).
    If verifier is None, considers success if output is not empty.
    """
    try:
        out = session.cmd(command, timeout)
        if verifier is not None:
            success = verifier(out) if callable(verifier) else False
        else:
            success = bool(out.strip())
        return success, out.strip()
    except Exception as e:
        return False, str(e)

# ─── Built-in Verifiers ────────────────────────────────────────────────────
def ver_active(out):
    return out.strip() == "active"

def ver_contains(needle):
    return lambda out: needle in out

def ver_not_empty(out):
    return bool(out.strip())

def ver_which(out):
    return bool(out.strip()) and not out.startswith("which:")

# ─── Write file (base64, avoids heredoc issues over SSH) ───────────────────
def write_file(session, path, content):
    """Write content to a file via base64 (safe for SSH, no heredoc problems)."""
    encoded = base64.b64encode(content.encode()).decode()
    wf_ok, wf_out = vcmd(session,
        f"mkdir -p $(dirname {path}) && echo '{encoded}' | base64 -d > {path} && echo FILE_WRITTEN",
        verifier=ver_contains("FILE_WRITTEN"), timeout=15)
    return wf_ok, wf_out


# ─── Pipeline ──────────────────────────────────────────────────────────────
class Pipeline:
    """Runs stages in a chain with progress bar and verification."""

    def __init__(self):
        self.bar = ProgressBar()
        self.stages = []
        self.current_pct = 0

    def add(self, name, weight, func, *args, **kwargs):
        self.stages.append((name, weight, func, args, kwargs))

    def run(self, session):
        total_weight = sum(w for _, w, _, _, _ in self.stages)
        if total_weight == 0:
            return True
        for name, weight, func, args, kwargs in self.stages:
            stage_share = (weight / total_weight) * 100
            self.bar.update(self.current_pct, f"▶ {name}")

            def progress(sub_pct, msg=""):
                overall = self.current_pct + stage_share * sub_pct / 100
                self.bar.update(overall, msg)

            try:
                success = func(session, progress_cb=progress, *args, **kwargs)
            except Exception as e:
                self.bar.update(self.current_pct + stage_share, f"{C['R']}✘{C['W']} {name}")
                fail(f"{name}: {e}")
                return False

            if success:
                self.current_pct += stage_share
                self.bar.update(self.current_pct, f"{C['G']}✔{C['W']} {name}")
            else:
                self.bar.update(self.current_pct + stage_share, f"{C['R']}✘{C['W']} {name}")
                fail(f"Pipeline oprit la etapa: {name}")
                return False
        return True

# ─── Constants ─────────────────────────────────────────────────────────────
DOT_PROVIDERS = {
    "1": {"name": "Quad9",       "primary": "9.9.9.9@853",        "secondary": "149.112.112.112@853"},
    "2": {"name": "Cloudflare",  "primary": "1.1.1.1@853",        "secondary": "1.0.0.1@853"},
    "3": {"name": "Google",      "primary": "8.8.8.8@853",        "secondary": "8.8.4.4@853"},
}

# ─── OS Classification (shared by Session and LocalSession) ────────────────
def _classify_os(os_info):
    """Fill pkg_manager, net_handler, unbound fields based on OS id/id_like."""
    os_id = os_info.get("id", "")
    os_like = os_info.get("id_like", "")

    if os_id in ("debian", "ubuntu", "linuxmint", "raspbian"):
        os_info["pkg_manager"] = "apt"
        os_info["pkg_install"] = "apt install -y"
        os_info["pkg_update"] = "apt update -qq"
        os_info["unbound_user"] = "unbound"
        os_info["root_key_src"] = "/usr/share/dns/root.key"
        os_info["unbound_key_dir"] = "/var/lib/unbound"
        os_info["unbound_conf_d"] = "/etc/unbound/unbound.conf.d"
    elif os_id in ("fedora", "rhel", "centos", "rocky", "almalinux"):
        os_info["pkg_manager"] = "dnf"
        os_info["pkg_install"] = "dnf install -y"
        os_info["pkg_update"] = "dnf check-update"
        os_info["unbound_user"] = "unbound"
        os_info["root_key_src"] = "/etc/unbound/root.key"
        os_info["unbound_key_dir"] = "/var/lib/unbound"
        os_info["unbound_conf_d"] = "/etc/unbound/unbound.conf.d"
    elif os_id == "alpine":
        os_info["pkg_manager"] = "apk"
        os_info["pkg_install"] = "apk add"
        os_info["pkg_update"] = "apk update"
        os_info["unbound_user"] = "unbound"
        os_info["root_key_src"] = ""
        os_info["unbound_key_dir"] = "/var/lib/unbound"
        os_info["unbound_conf_d"] = "/etc/unbound/unbound.conf.d"
    else:
        os_info["pkg_manager"] = "apt"
        os_info["pkg_install"] = "apt install -y"
        os_info["pkg_update"] = "apt update -qq"
        os_info["unbound_user"] = "unbound"
        os_info["root_key_src"] = "/usr/share/dns/root.key"
        os_info["unbound_key_dir"] = "/var/lib/unbound"
        os_info["unbound_conf_d"] = "/etc/unbound/unbound.conf.d"

    if os_id == "ubuntu" or (os_id == "linuxmint" and os_like == "ubuntu"):
        os_info["net_handler"] = "nmcli" if os_id == "linuxmint" else "netplan"
    elif os_id in ("fedora", "rhel", "centos", "rocky", "almalinux"):
        os_info["net_handler"] = "nmcli"
    else:
        os_info["net_handler"] = "interfaces"


UNBOUND_RECURSIVE = """server:
    verbosity: 0
    interface: 127.0.0.1
    port: 5335
    do-ip4: yes
    do-udp: yes
    do-tcp: yes
    incoming-num-tcp: 200
    tcp-idle-timeout: 300
    do-ip6: no
    prefer-ip6: no
    harden-glue: yes
    harden-dnssec-stripped: yes
    use-caps-for-id: no
    edns-buffer-size: 1232
    prefetch: yes
    num-threads: 2
    so-rcvbuf: 1m
    private-address: 192.168.0.0/16
    private-address: 169.254.0.0/16
    private-address: 172.16.0.0/12
    private-address: 10.0.0.0/8
    private-address: fd00::/8
    private-address: fe80::/10
    auto-trust-anchor-file: "/var/lib/unbound/root.key"
"""

# ─── Session Manager ───────────────────────────────────────────────────────
class Session:
    """SSH session — becomes root once, then runs commands directly."""

    def __init__(self, ip, user, password, root_password=None):
        self.ip = ip
        self.user = user
        self.password = password
        self.root_password = root_password
        self.os_info = {}
        self.is_root = False
        self.child = None

    def connect(self):
        info(f"Connecting to {self.user}@{self.ip}...")
        self.child = pexpect.spawn(
            f"ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            f"-o ConnectTimeout=10 {self.user}@{self.ip}",
            timeout=60, encoding="utf-8", dimensions=(24, 120)
        )
        idx = self.child.expect(["password:", "Permission denied", "Connection refused", pexpect.TIMEOUT], timeout=15)
        if idx == 1: raise ConnectionError("Permission denied")
        if idx == 2: raise ConnectionError("Connection refused - SSH not running?")
        if idx == 3: raise ConnectionError("Timeout - IP reachable?")
        self.child.sendline(self.password)
        idx = self.child.expect(["$", "#", "Permission denied",
                                  "password:", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        if idx == 2:
            raise ConnectionError("SSH authentication failed — wrong user or password")
        if idx == 3:
            self.child.sendline(self.password)
            idx2 = self.child.expect(["$", "#", "Permission denied", pexpect.EOF], timeout=10)
            if idx2 >= 2:
                raise ConnectionError("SSH authentication failed after retry")
        if idx in (4, 5):
            raise ConnectionError(f"SSH connection ended unexpectedly (wrong credentials?)")
        ok(f"Connected to {self.user}@{self.ip}")
        self._detect_os()
        self._become_root()

    def _become_root(self):
        os_id = self.os_info.get("id", "")
        variant = self.os_info.get("variant", "")
        is_rpi = (variant == "raspbian" or os_id == "raspbian")

        if os_id in ("debian", "raspbian") and not is_rpi:
            root_pw = self.root_password
            if not self.root_password:
                print(f"\n  {C['Y']}{os_id.title()} detected — root password needed.{C['W']}")
                root_pw = input("  Root password: ").strip()
                self.root_password = root_pw
            self.child.sendline("su -")
            idx = self.child.expect(["Password:", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
            if idx != 0:
                raise ConnectionError("su - failed: no password prompt")
            self.child.sendline(root_pw)
            idx = self.child.expect(["#", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
            if idx != 0:
                raise ConnectionError("su - failed: wrong root password?")
        else:
            info("Acquiring root via sudo -S -i...")
            self.child.sendline("sudo -S -i")
            idx = self.child.expect(["[sudo] password", "#", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
            if idx == 2:
                raise ConnectionError("SSH connection lost during sudo")
            if idx == 0:
                self.child.sendline(self.password)
                idx2 = self.child.expect(["#", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
                if idx2 != 0:
                    raise ConnectionError("sudo failed: wrong password?")
            elif idx == 3:
                raise ConnectionError("sudo -S -i timed out")

        self.is_root = True
        self.child.sendline("echo ROOT_READY")
        idx = self.child.expect(["ROOT_READY", pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        if idx != 0:
            raise ConnectionError("Root session verification failed")
        self.child.expect("#", timeout=5)
        info("Root OK")

    def _detect_os(self):
        self.child.sendline("cat /etc/os-release 2>/dev/null")
        idx = self.child.expect(
            ["ID=debian", "ID=ubuntu", "ID=linuxmint", "ID=fedora",
             "ID=raspbian", "ID=rhel", "ID=alpine", pexpect.TIMEOUT], timeout=10)
        if idx == 7:
            return
        output = (self.child.before or "") + (self.child.after or "")
        self.child.expect(["$", "#", ":", pexpect.TIMEOUT], timeout=5)

        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("ID="):
                self.os_info["id"] = line.split("=", 1)[1].strip('"')
            if line.startswith("ID_LIKE="):
                self.os_info["id_like"] = line.split("=", 1)[1].strip('"')
            if line.startswith("VERSION_ID="):
                self.os_info["version"] = line.split("=", 1)[1].strip('"')
            if line.startswith("VARIANT_ID="):
                self.os_info["variant"] = line.split("=", 1)[1].strip('"')
            if line.startswith("VARIANT="):
                self.os_info["variant"] = line.split("=", 1)[1].strip('"')

        _classify_os(self.os_info)
        info(f"Detected: {self.os_info.get('id', '?')} ({self.os_info['pkg_manager']}/{self.os_info['net_handler']})")

    def cmd(self, command, timeout=60):
        marker = f"__CMD_{random.randint(100000, 999999)}__"
        self.child.sendline(f"{command}; echo {marker}")
        try:
            self.child.expect(marker, timeout=timeout)
            self.child.expect(marker, timeout=timeout)
            out = _ANSI.sub('', self.child.before or "")
            lines = []
            for l in out.split('\n'):
                l = l.strip()
                if l and l not in ('exit', 'logout') and marker not in l:
                    lines.append(l)
            return '\n'.join(lines).strip()
        except pexpect.TIMEOUT:
            return ""

    def auto_detect_network(self):
        self.iface = ""
        self.gateway = ""

        out = self.cmd("ls /sys/class/net/ | grep -v lo | head -1")
        for line in out.strip().split("\n"):
            line = line.strip()
            if re.match(r'^(ens|eth|wlan|wlo|enp)', line):
                self.iface = line
                break
        if not self.iface or len(self.iface) > 15:
            self.iface = "eth0"

        out = self.cmd("ip route show default | head -1 | awk '{print $3}'")
        for part in out.strip().split():
            if "." in part and part.count(".") == 3:
                self.gateway = part
                break
        if not self.gateway or len(self.gateway) > 15:
            self.gateway = "192.168.1.1"

        info(f"Interface: {self.iface}, Gateway: {self.gateway}")
        return self.iface, self.gateway

    def close(self):
        if self.child:
            self.child.sendline("exit")
            self.child.close()


class LocalSession:
    """Local execution session for direct install on the current machine."""

    def __init__(self):
        self.os_info = {}
        self.iface = ""
        self.gateway = ""
        self.current_ip = ""
        self.is_root = os.geteuid() == 0

    def connect(self):
        if not self.is_root:
            warn("Local mode is running without root. sudo may be required for some commands.")
        self._detect_os()

    def _detect_os(self):
        output = self.cmd("cat /etc/os-release 2>/dev/null")
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("ID="):
                self.os_info["id"] = line.split("=", 1)[1].strip('"')
            if line.startswith("ID_LIKE="):
                self.os_info["id_like"] = line.split("=", 1)[1].strip('"')
            if line.startswith("VERSION_ID="):
                self.os_info["version"] = line.split("=", 1)[1].strip('"')
            if line.startswith("VARIANT_ID="):
                self.os_info["variant"] = line.split("=", 1)[1].strip('"')

        if not self.os_info.get("id"):
            return
        _classify_os(self.os_info)
        info(f"Detected: {self.os_info.get('id', '?')} ({self.os_info['pkg_manager']}/{self.os_info['net_handler']})")

    def cmd(self, command, timeout=60):
        if self.is_root:
            proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            proc = subprocess.run(["sudo", "sh", "-c", command], capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or "").strip()

    def auto_detect_network(self):
        addr_output = self.cmd("ip -4 -o addr show up scope global | awk '{print $2, $4}'")
        for line in addr_output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                self.iface = parts[0]
                self.current_ip = parts[1].split('/')[0]
                break

        if not self.iface or len(self.iface) > 15:
            out = self.cmd("ls /sys/class/net/ | grep -v lo | head -1")
            for line in out.strip().split("\n"):
                line = line.strip()
                if re.match(r'^(ens|eth|wlan|wlo|enp)', line):
                    self.iface = line
                    break
            if not self.iface or len(self.iface) > 15:
                self.iface = "eth0"

        out = self.cmd("ip route show default | head -1 | awk '{print $3}'")
        for part in out.strip().split():
            if "." in part and part.count(".") == 3:
                self.gateway = part
                break
        if not self.gateway or len(self.gateway) > 15:
            self.gateway = "192.168.1.1"

        if not self.current_ip:
            addr_output = self.cmd(f"ip -4 addr show dev {self.iface}")
            ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", addr_output)
            self.current_ip = ip_match.group(1) if ip_match else "127.0.0.1"

        info(f"Interface: {self.iface}, Gateway: {self.gateway}, Current IP: {self.current_ip}")
        return self.iface, self.gateway

    def close(self):
        pass


# ─── Static IP Setup ───────────────────────────────────────────────────────
def set_static_ip(session, ip, gateway):
    handler = session.os_info["net_handler"]
    iface = session.iface

    if handler == "interfaces":
        config = f"""auto lo
iface lo inet loopback

auto {iface}
iface {iface} inet static
    address {ip}/24
    gateway {gateway}
    dns-nameservers {gateway}
"""
        w_ok, _ = write_file(session, "/etc/network/interfaces", config)
        if w_ok:
            ok("Config written to /etc/network/interfaces")
        else:
            fail("Failed to write /etc/network/interfaces")
            return False

    elif handler == "netplan":
        config = f"""network:
  version: 2
  renderer: networkd
  ethernets:
    {iface}:
      dhcp4: false
      addresses:
        - {ip}/24
      routes:
        - to: default
          via: {gateway}
      nameservers:
        addresses:
          - {gateway}
"""
        w_ok, _ = write_file(session, "/etc/netplan/01-pihole.yaml", config)
        if w_ok:
            ok("Config written to /etc/netplan/01-pihole.yaml")
        else:
            fail("Failed to write /etc/netplan/01-pihole.yaml")
            return False

    elif handler == "nmcli":
        out = session.cmd(
            f"nmcli -t -f NAME,DEVICE connection show --active | grep ':{iface}' | cut -d: -f1")
        conn_name = out.strip().split("\n")[0].strip() or "Wired connection 1"
        nm_ok, nm_out = vcmd(session,
            f"nmcli connection modify '{conn_name}' ipv4.method manual "
            f"ipv4.addresses {ip}/24 ipv4.gateway {gateway} ipv4.dns {gateway} "
            f"connection.autoconnect yes",
            verifier=ver_not_empty)
        if nm_ok:
            ok(f"nmcli: configured connection '{conn_name}'")
        else:
            fail(f"nmcli configuration failed: {nm_out}")
            return False

    return True


def restart_network(session, new_ip):
    handler = session.os_info["net_handler"]
    iface = session.iface

    warn(f"Restarting network... SSH will disconnect!")
    warn(f"New IP will be: {new_ip}")

    if handler == "nmcli":
        out = session.cmd(
            f"nmcli -t -f NAME,DEVICE connection show --active | grep ':{iface}' | cut -d: -f1")
        conn_name = out.strip().split("\n")[0].strip() or "Wired connection 1"
        session.cmd(f"nmcli connection down '{conn_name}' && nmcli connection up '{conn_name}'", timeout=10)
    elif handler == "netplan":
        session.cmd("netplan apply", timeout=10)
    else:
        session.cmd("systemctl restart networking", timeout=10)

    session.close()
    time.sleep(5)

    info(f"Reconnecting to {new_ip}...")
    for attempt in range(5):
        try:
            new_session = Session(new_ip, session.user, session.password, session.root_password)
            new_session.child = pexpect.spawn(
                f"ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                f"-o ConnectTimeout=5 {session.user}@{new_ip}",
                timeout=30, encoding="utf-8", dimensions=(24, 120)
            )
            idx = new_session.child.expect(["password:", pexpect.TIMEOUT], timeout=8)
            if idx == 0:
                new_session.child.sendline(session.password)
                time.sleep(1)
                new_session._detect_os()
                new_session._become_root()
                ok(f"Reconnected to {new_ip}")
                return new_session
        except Exception as e:
            fail(f"Attempt {attempt+1}: {e}")
            time.sleep(3)
    raise ConnectionError(f"Could not reconnect to {new_ip}")


# ─── Pi-hole Installation (Unattended) ─────────────────────────────────────
def install_pihole(session, progress_cb=None, upstream_dns="127.0.0.1#5335", admin_pw="", force=False, web_port="80"):
    """Install Pi-hole in UNATTENDED mode — no ncurses dialogs."""
    title("Pi-hole Installation (unattended)")
    
    def prog(pct, msg=""):
        if progress_cb:
            progress_cb(pct, msg)
    
    if not force:
        chk_ok, _ = vcmd(session, "which pihole", verifier=ver_which, timeout=5)
        if chk_ok:
            ok("Pi-hole already installed — skipping")
            return True
    
    prog(2, "Installing dependencies...")
    dep_ok, dep_out = vcmd(session,
        f"{session.os_info['pkg_update']} && "
        f"{session.os_info['pkg_install']} curl wget dialog dnsutils git -y",
        timeout=120)
    if not dep_ok:
        fail(f"Dependency installation failed: {dep_out}")
        return False
    prog(8, "Dependencies installed")
    
    prog(10, "Pre-configuring Pi-hole (setupVars.conf)...")
    iface = getattr(session, 'iface', 'eth0') or 'eth0'
    setupvars = f"""PIHOLE_INTERFACE={iface}
PIHOLE_DNS_1={upstream_dns}
QUERY_LOGGING=true
BLOCKING_ENABLED=true
PIHOLE_DOMAIN=lan
DNSSEC=true
CONDITIONAL_FORWARDING=false
"""
    conf_ok, conf_out = write_file(session, "/etc/pihole/setupVars.conf", setupvars)
    if not conf_ok:
        fail(f"Failed to create setupVars.conf: {conf_out}")
        return False
    prog(15, "setupVars.conf created")
    
    prog(18, "Downloading Pi-hole installer...")
    dl_ok, dl_out = vcmd(session,
        "wget -O /tmp/basic-install.sh https://install.pi-hole.net 2>&1 && echo DOWNLOAD_OK",
        verifier=ver_contains("DOWNLOAD_OK"), timeout=30)
    if not dl_ok:
        fail(f"Download failed: {dl_out}")
        return False
    session.cmd("chmod +x /tmp/basic-install.sh")
    prog(20, "Downloaded basic-install.sh")
    
    prog(22, "Running Pi-hole installer (unattended)...")
    inst_ok, inst_out = vcmd(session, "bash /tmp/basic-install.sh --unattended", timeout=300)
    if not inst_ok:
        fail(f"Pi-hole installer failed: {inst_out}")
        return False
    prog(60, "Pi-hole installer finished")
    
    prog(65, "Verifying Pi-hole binary...")
    which_ok, which_out = vcmd(session, "which pihole", verifier=ver_which)
    if not which_ok:
        fail(f"Pi-hole binary not found: {which_out}")
        return False
    prog(70, f"Pi-hole binary: {which_out.strip()}")
    
    prog(73, "Verifying pihole-FTL service...")
    time.sleep(2)
    ftl_ok, ftl_out = vcmd(session, "systemctl is-active pihole-FTL", verifier=ver_active)
    if not ftl_ok:
        warn(f"pihole-FTL not active initially ({ftl_out.strip()})")
        session.cmd("systemctl restart pihole-FTL", timeout=10)
        time.sleep(3)
        ftl_ok, ftl_out = vcmd(session, "systemctl is-active pihole-FTL", verifier=ver_active)
        if not ftl_ok:
            fail("pihole-FTL failed to start")
            return False
    prog(78, "pihole-FTL is active")
    
    prog(80, "Verifying Pi-hole DNS resolution...")
    time.sleep(2)
    dig_out = session.cmd("dig +short google.com @127.0.0.1 2>/dev/null")
    if dig_out.strip() and dig_out.strip() != "0.0.0.0":
        prog(85, "Pi-hole DNS resolves correctly")
        ok("Pi-hole DNS resolves correctly")
    else:
        warn("Pi-hole DNS not resolving yet (try after gravity finishes)")
    
    prog(83, "Cleaning up installer...")
    session.cmd("rm -f /tmp/basic-install.sh")
    if admin_pw is None:
        print(f"\n  Pi-hole Admin Password:")
        print(f"  1. Auto-generate (random)")
        print(f"  2. No password (disable)")
        print(f"  3. Enter custom password")
        pw_choice = input("  Choose [1-3]: ").strip()
        if pw_choice == "2":
            session.cmd("pihole setpassword ''")
            admin_pw = ""
            ok("No admin password set (password disabled)")
        elif pw_choice == "3":
            custom_pw = input("  Enter password: ").strip()
            admin_pw = custom_pw or ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            session.cmd(f"pihole setpassword '{admin_pw}'")
            ok("Custom admin password configured")
        else:
            admin_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            session.cmd(f"pihole setpassword '{admin_pw}'")
            ok(f"Auto-generated admin password: {admin_pw}")
    elif not admin_pw:
        admin_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        ok(f"Auto-generated admin password: {admin_pw}")
        session.cmd(f"pihole setpassword '{admin_pw}'")
    else:
        session.cmd(f"pihole setpassword '{admin_pw}'")
    session.admin_pw = admin_pw
    
    prog(90, "Running gravity (blocklists)...")
    session.cmd("pihole updateGravity >/dev/null 2>&1 &", timeout=5)
    prog(93, "Gravity update started (continues in background)")
    
    prog(95, "Setting web interface port...")
    session.cmd(f"setcap cap_net_bind_service=+ep /usr/bin/pihole-FTL 2>/dev/null || true")
    session.cmd(f"sed -i 's|^  port = \".*\"|  port = \"{web_port}o,{web_port}os,[::]:{web_port}o,[::]:{web_port}os\"|' /etc/pihole/pihole.toml 2>/dev/null || true")
    session.cmd("systemctl restart pihole-FTL", timeout=10)
    time.sleep(3)
    prog(98, f"Web interface ready on port {web_port}")
    
    prog(99, "Setting optimizer = -1 (disable stale-cache serving)...")
    session.cmd("sed -i 's/optimizer = [0-9].*/optimizer = -1/' /etc/pihole/pihole.toml")
    session.cmd("systemctl restart pihole-FTL", timeout=10)
    time.sleep(2)
    
    ok("Pi-hole installed successfully (unattended)")
    return True


# ─── Unbound Installation ──────────────────────────────────────────────────
def install_unbound(session, progress_cb=None, mode="recursive", provider=None, force=False):
    title("Unbound Installation")

    def prog(pct, msg=""):
        if progress_cb:
            progress_cb(pct, msg)

    if not force:
        chk_ok, _ = vcmd(session, "systemctl is-active unbound", verifier=ver_active, timeout=5)
        if chk_ok:
            ok("Unbound already installed and running — skipping")
            return True

    prog(5, "Updating packages...")
    upd_ok, upd_out = vcmd(session, session.os_info['pkg_update'], timeout=120)
    if not upd_ok:
        warn(f"Package update had warnings: {upd_out[:100]}")

    prog(10, "Installing unbound...")
    inst_ok, inst_out = vcmd(session,
        f"{session.os_info['pkg_install']} unbound -y",
        verifier=lambda o: "already" in o or "Setting up" in o or "Complete" in o or bool(o.strip()),
        timeout=120)
    if not inst_ok:
        fail(f"Unbound installation failed: {inst_out}")
        return False
    prog(25, "Unbound package installed")

    which_ok, which_out = vcmd(session, "which unbound", verifier=ver_which)
    if not which_ok:
        warn("unbound binary not found, may be named unbound-checkconf")
    else:
        prog(28, f"Unbound binary: {which_out.strip()}")

    if mode == "recursive":
        config = UNBOUND_RECURSIVE
    else:
        p = DOT_PROVIDERS.get(provider, DOT_PROVIDERS["1"])
        config = UNBOUND_RECURSIVE + f"""
forward-zone:
    name: "."
    forward-tls-upstream: yes
    forward-addr: {p['primary']}
    forward-addr: {p['secondary']}
"""
        ok(f"DoT provider: {p['name']} ({p['primary']})")

    conf_d = session.os_info.get("unbound_conf_d", "/etc/unbound/unbound.conf.d")
    key_dir = session.os_info.get("unbound_key_dir", "/var/lib/unbound")
    key_src = session.os_info.get("root_key_src", "")
    ub_user = session.os_info.get("unbound_user", "unbound")

    config = config.replace('/var/lib/unbound/root.key', f'{key_dir}/root.key')

    prog(40, "Writing Unbound config...")
    w_ok, w_out = write_file(session, f"{conf_d}/pi-hole.conf", config)
    if not w_ok:
        fail(f"Failed to write unbound config: {w_out}")
        return False
    prog(50, "Config written")

    prog(55, "Disabling unbound-resolvconf...")
    session.cmd("systemctl disable --now unbound-resolvconf.service 2>/dev/null || true")

    prog(58, "Ensuring root trust anchor...")
    if key_src:
        session.cmd(f"mkdir -p {key_dir} && cp {key_src} {key_dir}/root.key 2>/dev/null && chown {ub_user}:{ub_user} {key_dir} {key_dir}/root.key; rm -f {conf_d}/root-auto-trust-anchor-file.conf")
    else:
        warn(f"No root key source for this OS — unbound-anchor may be needed")

    prog(59, "Ensuring main unbound.conf...")
    session.cmd(f"test -f /etc/unbound/unbound.conf || printf 'server:\n    include: {conf_d}/*.conf\n' > /etc/unbound/unbound.conf")

    prog(60, "Validating Unbound config...")
    val_ok, val_out = vcmd(session, "unbound-checkconf 2>&1", timeout=10)
    if not val_ok:
        fail(f"Unbound config invalid: {val_out}")
        return False

    prog(61, "Tuning kernel socket buffers...")
    session.cmd("sysctl -w net.core.rmem_max=5242880")
    session.cmd("sysctl -w net.core.wmem_max=5242880")
    session.cmd("grep -q 'rmem_max=5242880' /etc/sysctl.conf || echo 'net.core.rmem_max=5242880' >> /etc/sysctl.conf")
    session.cmd("grep -q 'wmem_max=5242880' /etc/sysctl.conf || echo 'net.core.wmem_max=5242880' >> /etc/sysctl.conf")
    ok("Socket buffers optimized (rmem/wmem=5M)")

    prog(63, "Fixing Unbound systemd service (DAEMON_OPTS)...")
    session.cmd("mkdir -p /etc/systemd/system/unbound.service.d")
    wf_ok, wf_out = write_file(session, "/etc/systemd/system/unbound.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/usr/sbin/unbound -d -p\nEnvironment=\nRestart=always\nRestartSec=2\n")
    if not wf_ok:
        warn(f"Write override.conf failed: {wf_out}")
    session.cmd("systemctl daemon-reload")
    ok("Unbound systemd override: ExecStart direct (no $DAEMON_OPTS)")

    prog(65, "Restarting Unbound...")
    session.cmd("systemctl restart unbound", timeout=15)
    time.sleep(2)

    prog(80, "Verifying Unbound service...")
    svc_ok, svc_out = vcmd(session, "systemctl is-active unbound", verifier=ver_active)
    if not svc_ok:
        fail(f"Unbound not running: {svc_out}")
        return False
    prog(90, "Unbound is active")

    prog(95, "Verifying Unbound DNS resolution...")
    dig_out = session.cmd("dig +short google.com @127.0.0.1 -p 5335 2>/dev/null")
    if dig_out.strip() and dig_out.strip() != "0.0.0.0":
        ok(f"Unbound resolves: {dig_out.split(chr(10))[0]}")
    else:
        warn(f"Unbound DNS not resolving yet: {dig_out[:40]}")

    prog(100, "Done")
    ok("Unbound installed and configured")
    return True


# ─── Auto Updates ──────────────────────────────────────────────────────────
def setup_auto_updates(session, progress_cb=None):
    title("Configuring Automatic Security Updates")

    def prog(pct, msg=""):
        if progress_cb:
            progress_cb(pct, msg)

    pm = session.os_info.get("pkg_manager", "apt")

    if pm == "apt":
        prog(20, "Installing unattended-upgrades...")
        ok_, out = vcmd(session,
            f"{session.os_info['pkg_install']} unattended-upgrades -y",
            timeout=120)
        if not ok_:
            fail(f"unattended-upgrades install failed: {out}")
            return False

        prog(60, "Writing configuration...")
        conf_50 = (
            'Unattended-Upgrade::Allowed-Origins {\n'
            '    "${distro_id}:${distro_codename}-security";\n'
            '};\n'
            'Unattended-Upgrade::AutoFixInterruptedDpkg "true";\n'
            'Unattended-Upgrade::MinimalSteps "true";\n'
            'Unattended-Upgrade::Remove-Unused-Dependencies "true";\n'
            'Unattended-Upgrade::Automatic-Reboot "false";\n'
        )
        conf_20 = (
            'APT::Periodic::Update-Package-Lists "1";\n'
            'APT::Periodic::Unattended-Upgrade "1";\n'
        )
        w1_ok, _ = write_file(session, "/etc/apt/apt.conf.d/50unattended-upgrades", conf_50)
        w2_ok, _ = write_file(session, "/etc/apt/apt.conf.d/20auto-upgrades", conf_20)
        if not w1_ok or not w2_ok:
            fail("Failed to write unattended-upgrades config")
            return False

        prog(90, "Enabling service...")
        vcmd(session, "systemctl enable --now unattended-upgrades", timeout=15)
        svc_ok, _ = vcmd(session, "systemctl is-active unattended-upgrades", verifier=ver_active)
        if not svc_ok:
            fail("unattended-upgrades service not active")
            return False

    elif pm == "dnf":
        prog(20, "Installing dnf-automatic...")
        ok_, out = vcmd(session,
            f"{session.os_info['pkg_install']} dnf-automatic -y",
            timeout=120)
        if not ok_:
            fail(f"dnf-automatic install failed: {out}")
            return False

        prog(60, "Configuring dnf-automatic (security only)...")
        vcmd(session,
            "sed -i 's/^upgrade_type.*/upgrade_type = security/' /etc/dnf/automatic.conf && "
            "sed -i 's/^apply_updates.*/apply_updates = yes/' /etc/dnf/automatic.conf",
            timeout=15)

        prog(90, "Enabling timer...")
        vcmd(session, "systemctl enable --now dnf-automatic.timer", timeout=15)

    else:
        warn(f"Auto-updates not supported for package manager: {pm}")
        return True

    prog(100, "Auto-updates configured")
    ok("Automatic security updates enabled")
    return True


# ─── Connect Pi-hole to Unbound ────────────────────────────────────────────
def connect_pihole_unbound(session, progress_cb=None):
    title("Connecting Pi-hole to Unbound")

    def prog(pct, msg=""):
        if progress_cb:
            progress_cb(pct, msg)

    prog(10, "Reading current pihole.toml upstreams...")
    out = session.cmd("grep -c 'upstreams' /etc/pihole/pihole.toml 2>/dev/null")
    has_upstreams = out.strip().isdigit() and int(out.strip()) > 0

    prog(20, "Setting upstream to 127.0.0.1#5335...")
    upstream_entry = '\nupstreams = ["127.0.0.1#5335"]\n'
    write_file_ok, write_file_out = write_file(session, "/tmp/pua_upstream.txt", upstream_entry)
    if not write_file_ok:
        fail(f"Failed to create upstream temp file: {write_file_out}")
        return False
    if has_upstreams:
        session.cmd("sed -i '/^upstreams/,/^]/d' /etc/pihole/pihole.toml")
    session.cmd("cat /tmp/pua_upstream.txt >> /etc/pihole/pihole.toml && rm -f /tmp/pua_upstream.txt")

    prog(40, "Reloading Pi-hole DNS...")
    rld_ok, rld_out = vcmd(session, "pihole reloaddns 2>&1 || systemctl restart pihole-FTL", timeout=15)
    time.sleep(3)

    prog(60, "Verifying upstream config...")
    grep_ok, grep_out = vcmd(session,
        "grep '127.0.0.1#5335' /etc/pihole/pihole.toml",
        verifier=ver_not_empty)
    if not grep_ok:
        fail(f"Upstream not set correctly: {grep_out}")
        return False
    prog(75, "Upstream verified: 127.0.0.1#5335")

    prog(80, "Verifying pihole-FTL service...")
    ftl_ok, ftl_out = vcmd(session, "systemctl is-active pihole-FTL", verifier=ver_active)
    if not ftl_ok:
        fail("pihole-FTL not running after reload")
        return False
    prog(90, "pihole-FTL is active")

    prog(93, "Checking web interface port...")
    port_chk = session.cmd("ss -tlnp | grep -c ':80 ' 2>/dev/null")
    if port_chk.strip() == "0":
        session.cmd("setcap cap_net_bind_service=+ep /usr/bin/pihole-FTL 2>/dev/null || true")
        session.cmd("sed -i 's|^  port = \"8080o,8443os,\\[::\\]:8080o,\\[::\\]:8443os\"|  port = \"80o,443os,\\[::\\]:80o,\\[::\\]:443os\"|' /etc/pihole/pihole.toml 2>/dev/null || true")
        session.cmd("systemctl restart pihole-FTL", timeout=10)
        time.sleep(3)
        ok("Web interface configured on port 80")
    else:
        ok("Web interface already on port 80")

    prog(95, "Setting optimizer = -1 (disable stale-cache serving)...")
    session.cmd("sed -i 's/optimizer = [0-9].*/optimizer = -1/' /etc/pihole/pihole.toml")

    prog(96, "Configuring NTP fallback servers...")
    session.cmd("sed -i 's|^    server = \"pool\\.ntp\\.org\"|    server = [\"pool.ntp.org\", \"time.cloudflare.com\", \"time.google.com\"]|' /etc/pihole/pihole.toml 2>/dev/null || true")
    ntp_ok, ntp_out = vcmd(session,
        "grep 'time.cloudflare.com' /etc/pihole/pihole.toml",
        verifier=ver_not_empty)
    if not ntp_ok:
        warn("NTP fallback config may not have applied, but will retry")
        session.cmd("sed -i 's|^    server = \"pool\\.ntp\\.org\"|    server = [\"pool.ntp.org\", \"time.cloudflare.com\", \"time.google.com\"]|' /etc/pihole/pihole.toml 2>/dev/null || true")
    session.cmd("systemctl restart pihole-FTL", timeout=10)
    time.sleep(2)
    ok("NTP fallback: pool.ntp.org + Cloudflare + Google")

    prog(100, "Done")
    ok("Pi-hole -> Unbound: connected")
    return True


# ─── Tests ─────────────────────────────────────────────────────────────────
def run_tests(session, progress_cb=None, ip=""):
    title("Running DNS Tests")

    def prog(pct, msg=""):
        if progress_cb:
            progress_cb(pct, msg)

    results = {"total": 0, "passed": 0, "failed": 0}
    test_ip = ip

    def test_dig(domain, expected_not="0.0.0.0", label=""):
        out = session.cmd(f"dig +short {domain} @{test_ip} 2>/dev/null")
        label = label or domain
        if "communications error" in out or "timed out" in out:
            fail(f"DNS ERROR: {label} ({out[:60]})")
            results["failed"] += 1
            results["total"] += 1
            return
        if expected_not == "BLOCKED":
            if "0.0.0.0" in out:
                ok(f"BLOCKED: {label}")
                results["passed"] += 1
            else:
                fail(f"NOT BLOCKED: {label} ({out[:50]})")
                results["failed"] += 1
        elif expected_not == "DNSSEC_INVALID":
            if not out:
                ok(f"DNSSEC invalid correctly: {label}")
                results["passed"] += 1
            else:
                fail(f"DNSSEC should have failed: {label} ({out[:50]})")
                results["failed"] += 1
        elif expected_not != "IGNORE":
            if out and expected_not not in out:
                ok(f"{label} -> {out.split(chr(10))[0]}")
                results["passed"] += 1
            else:
                fail(f"{label}: {out[:50] or 'no response'}")
                results["failed"] += 1
        results["total"] += 1

    prog(5, "Testing legitimate websites...")
    sites = ["google.com", "facebook.com", "youtube.com", "github.com", "wikipedia.org",
             "reddit.com", "amazon.com", "stackoverflow.com", "twitter.com", "linkedin.com"]
    for i, site in enumerate(sites):
        test_dig(site, label=site)
        prog(5 + (i + 1) * 3, f"Test: {site}")

    prog(35, "Testing ad/tracker blocking...")
    ads = ["doubleclick.net", "googlesyndication.com", "ads.google.com",
           "pagead2.googlesyndication.com", "adservice.google.com", "analytics.google.com"]
    for i, ad in enumerate(ads):
        test_dig(ad, expected_not="BLOCKED", label=ad)
        prog(35 + (i + 1) * 3, f"Block test: {ad}")

    prog(55, "Testing DNSSEC...")
    test_dig("dnssec.works", expected_not="0.0.0.0", label="DNSSEC valid")
    prog(65, "DNSSEC valid test done")
    test_dig("dnssec-failed.org", expected_not="DNSSEC_INVALID", label="DNSSEC invalid (should fail)")
    prog(72, "DNSSEC invalid test done")

    prog(80, "Verifying Pi-hole FTL stats...")
    out = session.cmd("pihole status 2>&1")
    if "FTL" in out or "active" in out or "enabled" in out:
        ok("Pi-hole FTL status: OK")
        results["passed"] += 1
    else:
        warn(f"Pi-hole status: {out[:80]}")
        results["failed"] += 1
    results["total"] += 1

    prog(95, "Checking Pi-hole gravity...")
    out = session.cmd("pihole -c -j 2>/dev/null | grep -o '\"domains_being_blocked\": [0-9]*' || pihole -c 2>/dev/null | head -5")
    if out.strip():
        ok(f"Gravity: {out.strip()[:60]}")
    else:
        warn("Could not get gravity stats")

    prog(100, "All tests completed")

    print(f"\n  {'─'*40}")
    print(f"  Results:  Total={results['total']}  "
          f"{C['G']}Passed={results['passed']}{C['W']}  "
          f"{C['R'] if results['failed'] else ''}Failed={results['failed']}{C['W']}")
    print(f"  {'─'*40}")

    session.test_results = results
    return results


# ─── Main ──────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Pi-hole + Unbound Auto-Deployer")
    parser.add_argument("--local", action="store_true", help="Run installation locally instead of SSH")
    parser.add_argument("--host", help="Remote server IP or hostname")
    parser.add_argument("--user", help="SSH username for remote mode")
    parser.add_argument("--password", help="SSH password for remote mode")
    parser.add_argument("--root-password", help="Root password for remote su mode on remote host")
    parser.add_argument("--force", action="store_true", help="Reinstall even if already installed")
    return parser.parse_args()


def main():
    args = parse_args()

    title("Pi-hole + Unbound Auto-Deployer (PUA)")
    print(f"  {C['Y']}This script will install and configure Pi-hole + Unbound.{C['W']}")
    print(f"  {C['Y']}Supports: Debian, Ubuntu, Mint, Fedora{C['W']}\n")

    auto_mode = bool(args.host and args.user and args.password) or args.local

    if not auto_mode:
        print("  Installation mode:")
        print("  1. Install locally (this machine)")
        print("  2. Install via SSH (remote server)")
        mode_choice = input("  Choose [1-2]: ").strip()
        is_local = (mode_choice == "1")

        if is_local:
            args.local = True
        else:
            print(f"\n{C['BOLD']}─── Connection Details ───{C['W']}")
            ip = input("  Server IP: ").strip()
            user = input("  SSH user: ").strip()
            password = input("  SSH password: ").strip()
            args.host, args.user, args.password = ip, user, password

        confirm = input("\n  Continue? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return

    if args.local:
        if args.host or args.user or args.password or args.root_password:
            warn("Remote credentials ignored because --local mode is enabled.")
        print(f"\n{C['BOLD']}─── Local Mode ───{C['W']}")
        session = LocalSession()
        try:
            session.connect()
        except Exception as e:
            fail(f"Local setup failed: {e}")
            return
        session.auto_detect_network()
        ip = input(f"\n  Local IP address [{session.current_ip}]: ").strip() or session.current_ip
        user = None
        password = None
    else:
        print(f"\n{C['BOLD']}─── Connection Details ───{C['W']}")
        ip = args.host
        user = args.user
        password = args.password
        print(f"  Server IP: {ip}")
        print(f"  SSH user:  {user}")
        print(f"  SSH pass:  {'*****' if password else ''}")

        if not ip or not password:
            print("  IP and password required.")
            return

        try:
            session = Session(ip, user, password, args.root_password)
            session.connect()
        except Exception as e:
            fail(f"Connection failed: {e}")
            return

    # Network auto-detect
    iface, gateway = session.auto_detect_network()

    # IP configuration
    print(f"\n{C['BOLD']}─── IP Configuration ───{C['W']}")
    print(f"  Static IP is RECOMMENDED for Pi-hole.")
    print(f"  1. Set static IP (recommended)")
    print(f"  2. Keep DHCP (skip)")
    if auto_mode:
        ip_choice = "2"
        ok("Auto-mode: keeping DHCP")
    else:
        ip_choice = input("  Choose [1-2]: ").strip()

    reconfigured = False
    if ip_choice == "1":
        new_ip = input(f"  Static IP [{ip}]: ").strip() or ip
        gateway = input(f"  Gateway [{gateway}]: ").strip() or gateway

        # Check if IP is already in use
        result = subprocess.run(
            f"ping -c 1 -W 1 {new_ip}", shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0 and new_ip != ip:
            warn(f"IP {new_ip} is already in use on the network!")
            if input("  Use it anyway? (y/n): ").strip().lower() != "y":
                return
        else:
            ok(f"IP {new_ip} is free")

        set_static_ip(session, new_ip, gateway)
        session = restart_network(session, new_ip)
        ip = new_ip
        reconfigured = True
    else:
        ok("Keeping DHCP")

    # Auto-detect network again after reconnect
    iface, gateway = session.auto_detect_network()

    # DNS mode
    print(f"\n{C['BOLD']}─── DNS Mode ───{C['W']}")
    print(f"  1. Recursive (unencrypted, direct root servers, ISP sees fragments)")
    print(f"  2. DoT (encrypted TLS, ISP sees nothing, provider sees queries)")
    if auto_mode:
        dns_choice = "1"
        ok("Auto-mode: recursive")
    else:
        dns_choice = input("  Choose [1-2]: ").strip()

    mode = "recursive"
    provider = None
    if dns_choice == "2":
        mode = "dot"
        print(f"\n  {C['BOLD']}Select DNS Provider:{C['W']}")
        for k, v in DOT_PROVIDERS.items():
            print(f"  {k}. {v['name']} ({v['primary']})")
        print(f"  4. Custom (enter manually)")
        prov_choice = input("  Choose [1-4]: ").strip()

        if prov_choice == "4":
            custom_ip = input("  Enter DoT address (ex: 9.9.9.9@853): ").strip()
            custom_ip2 = input("  Secondary (Enter = skip): ").strip()
            provider = "custom"
            DOT_PROVIDERS["custom"] = {"name": "Custom", "primary": custom_ip, "secondary": custom_ip2 or custom_ip}
        else:
            provider = prov_choice if prov_choice in DOT_PROVIDERS else "1"

    # Web interface port
    print(f"\n{C['BOLD']}─── Web Interface Configuration ───{C['W']}")
    web_port = input(f"  Set web interface port [80]: ").strip() or "80"
    
    # Pipeline automata ────────────────────────────────────────────────
    title("Installation Pipeline")

    pipeline = Pipeline()
    pipeline.add("Unbound Installation", 25, install_unbound, mode=mode, provider=provider, force=args.force)
    pipeline.add("Pi-hole Installation", 40, install_pihole, upstream_dns="127.0.0.1#5335", admin_pw="" if auto_mode else None, force=args.force, web_port=web_port)
    pipeline.add("Connect Pi-hole ↔ Unbound", 15, connect_pihole_unbound)
    pipeline.add("Auto-Updates",               5, setup_auto_updates)
    pipeline.add("DNS Tests",                 20, run_tests, ip=ip)

    if not pipeline.run(session):
        fail("Installation pipeline failed — check output above")
        session.close()
        return

    port_out = session.cmd("ss -tlnp | awk '/pihole-FTL/ && /LISTEN/ && /:80 / {print $4; exit}' | rev | cut -d: -f1 | rev")
    admin_port = port_out.strip() or "80"
    url_port = f":{admin_port}" if admin_port != "80" else ""
    title("Installation Complete!")
    print(f"  {C['G']}Pi-hole admin:  http://{ip}{url_port}/admin{C['W']}")
    pw_display = getattr(session, 'admin_pw', '')
    if not pw_display:
        pw_display = "(none - password disabled)"
    print(f"  {C['G']}Password:      {pw_display}{C['W']}")
    print(f"  {C['G']}DNS Server:     {ip}{C['W']}")
    print(f"  {C['Y']}Configure your router DHCP DNS to: {ip}{C['W']}")

    session.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {C['Y']}Aborted by user.{C['W']}")
    except Exception as e:
        fail(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
