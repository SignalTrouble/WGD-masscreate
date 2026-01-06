#!/usr/bin/env python3
"""
WireGuard Massenkonfigurations-Generator für WGDashboard-API.

"""

from __future__ import annotations

import argparse
import configparser
import getpass
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

# Farbcodes (wie im alten Skript)
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"

DEFAULT_CONFIG_PATH = "config.ini"


# Hilfsfunktionen
def run_cmd(
    cmd: List[str],
    *,
    capture: bool = False,
    check: bool = True,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess:
    """Wrapper um subprocess.run mit vereinheitlichter Fehlerbehandlung."""
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=False if input_data else True,
        input=input_data,
    )


def check_dependencies() -> None:
    missing = []
    for binary in ("wg", "wg-quick", "ip", "systemctl"):
        if shutil.which(binary) is None:  # type: ignore[name-defined]
            missing.append(binary)
    if missing:
        print(f"{RED}Fehler: Fehlende Abhängigkeiten: {', '.join(missing)}{NC}")
        sys.exit(1)


def prompt_if_empty(value: str | None, prompt_text: str, secret: bool = False) -> str:
    if value:
        return value
    if secret:
        return getpass.getpass(prompt_text)
    return input(prompt_text)


def format_number(num: int, digits: int) -> str:
    return f"{num:0{digits}d}"


def api_handshake(url: str, api_key: str, timeout: int = 5) -> bool:
    req = Request(f"{url}/api/handshake", headers={"wg-dashboard-apikey": api_key})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, HTTPError):
        return False


def update_wgdashboard_peer(
    url: str,
    api_key: str,
    config_name: str,
    peer_pubkey: str,
    peer_privkey: str,
    peer_name: str,
    peer_dns: str,
    peer_allowed_ips: str,
    endpoint_allowed_ips: str,
    peer_mtu: int,
    peer_keepalive: int,
    server_endpoint: str,
) -> bool:
    payload = json.dumps(
        {
            "id": peer_pubkey,
            "name": peer_name,
            "private_key": peer_privkey,
            "DNS": peer_dns,
            "allowed_ip": peer_allowed_ips,
            "endpoint_allowed_ip": endpoint_allowed_ips,
            "preshared_key": "",
            "mtu": peer_mtu,
            "keepalive": peer_keepalive,
            "remote_endpoint": server_endpoint,
        }
    ).encode()

    req = Request(
        f"{url}/api/updatePeerSettings/{config_name}",
        data=payload,
        headers={
            "wg-dashboard-apikey": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode() or "{}")
            return bool(body.get("status") is True)
    except (URLError, HTTPError, json.JSONDecodeError):
        return False


def create_config_text(
    address: str,
    listen_port: str,
    interface_privkey: str,
    extra_peers: List[Dict[str, str]],
) -> str:
    lines: List[str] = [
        "[Interface]",
        f"Address = {address}",
        "SaveConfig = true",
        "PreUp =",
        "PostUp =",
        "PreDown =",
        "PostDown =",
        f"ListenPort = {listen_port}",
        f"PrivateKey = {interface_privkey}",
        "",
    ]
    for peer in extra_peers:
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer['public_key']}")
        lines.append(f"AllowedIPs = {peer['allowed_ips']}")
        if peer.get("endpoint"):
            lines.append(f"Endpoint = {peer['endpoint']}")
        if peer.get("keepalive"):
            lines.append(f"PersistentKeepalive = {peer['keepalive']}")
        lines.append("")
    return "\n".join(lines)


def interface_running(name: str) -> bool:
    return run_cmd(["ip", "link", "show", name], check=False, capture=True).returncode == 0


def start_interface(name: str) -> bool:
    if interface_running(name):
        return True
    return run_cmd(["wg-quick", "up", name], check=False, capture=True).returncode == 0


def stop_interface(name: str) -> None:
    if not interface_running(name):
        return
    # wg-quick down reicht meist, fallback ip link delete
    if run_cmd(["wg-quick", "down", name], check=False, capture=True).returncode != 0:
        run_cmd(["ip", "link", "delete", name], check=False, capture=True)


def delete_interface_and_routes(name: str, peer_allowed_ips: str) -> None:
    # Interface stoppen und löschen
    stop_interface(name)
    run_cmd(["ip", "link", "delete", name], check=False, capture=True)
    # Routen entfernen, soweit sie bekannt sind
    for raw_ip in peer_allowed_ips.split(","):
        ip_cidr = raw_ip.strip()
        if not ip_cidr:
            continue
        run_cmd(["ip", "-4", "route", "delete", ip_cidr, "dev", name], check=False, capture=True)


def generate_keypair() -> Tuple[str, str]:
    priv = run_cmd(["wg", "genkey"], capture=True).stdout.strip()
    # wg pubkey liest den PrivateKey über stdin; als Bytes übergeben
    pub = run_cmd(
        ["wg", "pubkey"],
        capture=True,
        input_data=(priv + "\n").encode(),
    ).stdout.strip()
    return priv, pub.decode()


def purge_wgdashboard_tables(db_path: Path, pattern: str = "APW%") -> List[str]:
    cleared: List[str] = []
    if not db_path.exists():
        print(f"{YELLOW}Warnung: DB {db_path} nicht gefunden, überspringe Bereinigung.{NC}")
        return cleared

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", (pattern,))
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute(f'DELETE FROM "{table}"')
            cleared.append(table)
        conn.commit()
    finally:
        conn.close()
    return cleared


def purge_wgdashboard_tables_for(db_path: Path, names: List[str]) -> List[str]:
    """Leere nur Tabellen, deren Name mit einem der gegebenen Namen beginnt."""
    cleared: List[str] = []
    if not db_path.exists():
        print(f"{YELLOW}Warnung: DB {db_path} nicht gefunden, überspringe DB-Cleanup.{NC}")
        return cleared
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        patterns = tuple(f"{n}%" for n in names)
        query = "SELECT name FROM sqlite_master WHERE type='table' AND (" + " OR ".join(["name LIKE ?"] * len(patterns)) + ")"
        cur.execute(query, patterns)
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute(f'DELETE FROM "{table}"')
            cleared.append(table)
        conn.commit()
    finally:
        conn.close()
    return cleared


def restart_service(name: str, action: str) -> bool:
    return run_cmd(["systemctl", action, name], check=False).returncode == 0


def ensure_service_active(name: str, timeout: int = 10, interval: float = 1.0) -> bool:
    """Warte bis ein systemd Service aktiv ist."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        if run_cmd(["systemctl", "is-active", "--quiet", name], check=False).returncode == 0:
            return True
        time.sleep(interval)
    return False


def run_pre_creation_cleanup(db_path: Path, service: str) -> None:
    print(f"  {CYAN}Bereinige WGDashboard-DB...{NC}")
    restarted = False
    if restart_service(service, "stop"):
        restarted = True
    cleared = purge_wgdashboard_tables(db_path)
    if cleared:
        print(f"    Tabellen geleert!")
    else:
        print("    Keine passenden Tabellen gefunden.")
    if restarted:
        restart_service(service, "start")
        if not ensure_service_active(service):
            print(f"{RED}Fehler: {service} läuft nach Start nicht.{NC}")
            sys.exit(1)


def delete_existing_configs(target_dir: Path, allowed_names: set[str] | None = None) -> None:
    print(f"{YELLOW}Lösche bestehende Konfigurationen...{NC}")
    count = 0
    for conf_file in target_dir.glob("*.conf"):
        if conf_file.name.startswith("_"):
            print(f"  {CYAN}Überspringe: {conf_file} (beginnt mit _) {NC}")
            continue
        conf_name = conf_file.stem
        if allowed_names is not None and conf_name not in allowed_names:
            continue
        try:
            conf_file.unlink()
            count += 1
            print(f"  {GREEN}Gelöscht:{NC} {conf_file}")
        except OSError as exc:
            print(f"  {RED}Fehler beim Löschen {conf_file}: {exc}{NC}")
    print(f"  {count} Konfiguration(en) verarbeitet.\n")


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(f"{RED}Fehler: config.ini fehlt (erwartet: {path}).{NC}")
        sys.exit(1)

    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["defaults"] if "defaults" in parser else parser["DEFAULT"]

    required_str = [
        "address",
        "listen_port",
        "peer_allowed_ips",
        "target_dir",
        "peer_name",
        "server_endpoint",
        "peer_dns",
        "endpoint_allowed_ips",
        "dashboard_url",
        "dashboard_db",
        "dashboard_service",
    ]
    required_int = ["peer_mtu", "peer_keepalive"]

    cfg: Dict[str, Any] = {}

    for key in required_str:
        if key not in section or not section.get(key):
            print(f"{RED}Fehler: Schlüssel '{key}' fehlt in {path}.{NC}")
            sys.exit(1)
        cfg[key] = section.get(key)

    for key in required_int:
        try:
            cfg[key] = section.getint(key)
        except (ValueError, TypeError):
            print(f"{RED}Fehler: Schlüssel '{key}' muss Integer sein in {path}.{NC}")
            sys.exit(1)

    # Zusätzliche Peers aus Sektionen [peer.<name>]
    extra_peers: List[Dict[str, str]] = []
    for sec_name in parser.sections():
        if sec_name.lower().startswith("peer."):
            sec = parser[sec_name]
            allowed_ips = sec.get("allowed_ips", "").strip()
            endpoint = sec.get("endpoint", "").strip()
            keepalive = sec.get("keepalive", "").strip()
            name = sec_name.split(".", 1)[1] if "." in sec_name else sec_name
            if not allowed_ips:
                print(f"{RED}Fehler: peer-Sektion '{sec_name}' benötigt allowed_ips.{NC}")
                sys.exit(1)
            extra_peers.append(
                {
                    "name": name,
                    "public_key": sec.get("public_key", "").strip(),  # optional, wird bei Generierung ersetzt
                    "allowed_ips": allowed_ips,
                    "endpoint": endpoint,
                    "keepalive": keepalive,
                }
            )
    cfg["extra_peers"] = extra_peers
    if not extra_peers:
        print(f"{RED}Fehler: Mindestens ein Peer muss in der ini definiert sein (Sektion [peer.<name>]).{NC}")
        sys.exit(1)

    return cfg


def parse_args(defaults: Dict[str, Any], argv: List[str], config_path: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WireGuard Massenkonfigurations-Generator mit WGDashboard-Integration",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default=str(config_path), help="Pfad zur ini-Datei mit Standardwerten")
    parser.add_argument("-p", "--prefix", help="Präfix für Dateinamen (z.B. 'APW')")
    parser.add_argument("-s", "--start", type=int, help="Startnummer (z.B. 1)")
    parser.add_argument("-e", "--end", type=int, dest="end", help="Endnummer (z.B. 100)")
    parser.add_argument("-k", "--api-key", dest="api_key", help="WGDashboard API-Key")
    parser.add_argument("-d", "--dir", dest="target_dir", default=defaults["target_dir"], help="Zielverzeichnis")
    parser.add_argument("-a", "--address", default=defaults["address"], help="Interface-Adresse")
    parser.add_argument("-l", "--port", dest="listen_port", default=defaults["listen_port"], help="ListenPort")
    parser.add_argument("-i", "--allowed-ips", dest="peer_allowed_ips", default=defaults["peer_allowed_ips"], help="Peer AllowedIPs in Server-Konfig")
    parser.add_argument("--peer-name", default=defaults["peer_name"], help="Peer-Name in WGDashboard")
    parser.add_argument("--endpoint", dest="server_endpoint", default=defaults["server_endpoint"], help="Server-Endpoint für Client-Konfig")
    parser.add_argument("--delete-existing", action="store_true", help="Bestehende Konfigs löschen (außer _*)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    parser.add_argument("--dashboard-url", default=defaults["dashboard_url"], help="WGDashboard Basis-URL")
    parser.add_argument("--dashboard-db", default=defaults["dashboard_db"], help="Pfad zur WGDashboard SQLite DB")
    parser.add_argument("--dashboard-service", default=defaults["dashboard_service"], help="Service-Name von WGDashboard (systemctl)")
    parser.add_argument("--peer-dns", default=defaults["peer_dns"], help="DNS für Client")
    parser.add_argument("--peer-mtu", type=int, default=defaults["peer_mtu"], help="MTU für Client")
    parser.add_argument("--peer-keepalive", type=int, default=defaults["peer_keepalive"], help="PersistentKeepalive für Client")
    parser.add_argument("--endpoint-allowed-ips", default=defaults["endpoint_allowed_ips"], help="AllowedIPs in Client-Konfig")
    parser.add_argument("--delete-only", action="store_true", help="Nur löschen (angegebener Bereich): wg-quick down, Routen entfernen, .conf löschen, DB-Tabellen leeren")
    return parser.parse_args(argv)


def main() -> None:
    # Pass 1: nur --config einlesen
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    pre_args, remaining_argv = pre_parser.parse_known_args()

    config_path = Path(pre_args.config)
    defaults = load_config(config_path)

    args = parse_args(defaults, remaining_argv, config_path)
    extra_peers = defaults.get("extra_peers", [])

    # Interaktive Eingaben
    prefix = prompt_if_empty(args.prefix, "Präfix eingeben: ")
    start_num_str = prompt_if_empty(str(args.start) if args.start is not None else None, "Startnummer eingeben (z.B. 1): ")
    end_num_str = prompt_if_empty(str(args.end) if args.end is not None else None, "Endnummer eingeben (z.B. 10): ")
    api_key = prompt_if_empty(args.api_key, "WGDashboard API-Key eingeben: ", secret=True)

    # Validierung
    if not prefix or not start_num_str.isdigit() or not end_num_str.isdigit():
        print(f"{RED}Fehler: Präfix, Start- und Endnummer müssen angegeben und numerisch sein!{NC}")
        sys.exit(1)

    start_num = int(start_num_str)
    end_num = int(end_num_str)
    if start_num > end_num:
        print(f"{RED}Fehler: Startnummer muss kleiner oder gleich Endnummer sein!{NC}")
        sys.exit(1)
    if not api_key:
        print(f"{RED}Fehler: API-Key erforderlich!{NC}")
        sys.exit(1)

    # Einstellungen
    target_dir = Path(args.target_dir)
    digits = max(len(start_num_str), len(end_num_str))
    names_in_scope = {f"{prefix}{format_number(i, digits)}" for i in range(start_num, end_num + 1)}

    print("\n========================================")
    print(" WireGuard Konfigurations-Generator")
    print("========================================\n")
    print("Einstellungen:")
    print(f"  Präfix:        {prefix}")
    print(f"  Bereich:       {start_num} - {end_num}")
    print(f"  Ziel:          {target_dir}")
    print(f"  Address:       {args.address}")
    print(f"  ListenPort:    {args.listen_port}")
    print(f"  Peer-Name:     {args.peer_name}")
    print(f"  AllowedIPs:    {args.peer_allowed_ips}")
    print(f"  Endpoint:      {args.server_endpoint}")
    print(f"  Dashboard:     {args.dashboard_url}")
    if args.delete_existing:
        print(f"  {YELLOW}Lösche bestehende Konfigs!{NC}")
    if args.dry_run:
        print(f"  {YELLOW}Modus: DRY-RUN{NC}")
    print("")

    # API Test
    print("Teste API-Verbindung...", end=" ", flush=True)
    if not api_handshake(args.dashboard_url, api_key):
        print(f"{RED}Fehlgeschlagen{NC}")
        sys.exit(1)
    print(f"{GREEN}OK{NC}")

    # Zielverzeichnis
    if not args.dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(target_dir, os.W_OK):
            print(f"{RED}Fehler: Keine Schreibrechte für {target_dir}{NC}")
            sys.exit(1)

    if args.delete_existing and not args.dry_run:
        delete_existing_configs(target_dir, allowed_names=names_in_scope)

    # Nur-Löschmodus: selektiv im angegebenen Bereich löschen und beenden
    if args.delete_only:
        if args.dry_run:
            print(f"{YELLOW}[DRY-RUN] Lösche Bereich {start_num}-{end_num} mit Präfix {prefix}{NC}")
        names_to_delete = [f"{prefix}{format_number(i, digits)}" for i in range(start_num, end_num + 1)]
        db_path = Path(args.dashboard_db)
        if not args.dry_run:
            cleared = purge_wgdashboard_tables_for(db_path, names_to_delete)
            if cleared:
                print(f"{CYAN}DB-Tabellen geleert: {', '.join(cleared)}{NC}")
        for name in names_to_delete:
            filepath = target_dir / f"{name}.conf"
            if args.dry_run:
                print(f"{YELLOW}[DRY-RUN]{NC} Würde löschen: {filepath}")
                continue
            delete_interface_and_routes(name, args.peer_allowed_ips)
            if filepath.exists():
                filepath.unlink()
                print(f"{GREEN}Gelöscht:{NC} {filepath}")
        print(f"{GREEN}Löschlauf abgeschlossen.{NC}")
        return

    # WGDashboard-Bereinigung einmal vor dem Batch (statt vor jedem Interface)
    if not args.dry_run:
        run_pre_creation_cleanup(Path(args.dashboard_db), args.dashboard_service)

    # Zähler
    total = created = skipped = errors = 0
    summary: List[Tuple[str, str, List[Dict[str, str]]]] = []

    for i in range(start_num, end_num + 1):
        total += 1
        num = format_number(i, digits)
        config_name = f"{prefix}{num}"
        filepath = target_dir / f"{config_name}.conf"

        print(f"{CYAN}[{config_name}]{NC}")

        if filepath.exists() and not args.delete_existing:
            print(f"  {YELLOW}Existiert bereits, überspringe{NC}\n")
            skipped += 1
            continue

        try:
            interface_privkey, interface_pubkey = generate_keypair()
        except subprocess.CalledProcessError as exc:
            print(f"  {RED}Fehler bei Schlüsselerzeugung: {exc}{NC}")
            errors += 1
            continue

        print(f"  Interface-PrivKey: {interface_privkey[:15]}...")
        print(f"  Interface-PubKey:  {interface_pubkey[:15]}...")

        # Peer-Schlüsselpaare pro ini-Peer generieren
        peers_for_conf: List[Dict[str, str]] = []
        try:
            for peer in extra_peers:
                priv, pub = generate_keypair()
                peers_for_conf.append(
                    {
                        "name": peer.get("name", ""),
                        "public_key": pub,
                        "private_key": priv,
                        "allowed_ips": peer["allowed_ips"],
                        "endpoint": peer.get("endpoint", ""),
                        "keepalive": peer.get("keepalive", ""),
                    }
                )
        except subprocess.CalledProcessError as exc:
            print(f"  {RED}Fehler bei Peer-Schlüsselerzeugung: {exc}{NC}")
            errors += 1
            continue

        summary.append((config_name, interface_pubkey, peers_for_conf))

        if args.dry_run:
            print(f"  {YELLOW}[DRY-RUN] Würde erstellen: {filepath}{NC}\n")
            created += 1
            continue

        config_text = create_config_text(
            args.address,
            args.listen_port,
            interface_privkey,
            peers_for_conf,
        )
        filepath.write_text(config_text)
        os.chmod(filepath, 0o600)
        print(f"  {GREEN}Konfig erstellt: {filepath}{NC}\n")
        created += 1

    # API Updates (alle Peers je Config werden ans Dashboard übertragen)
    if not args.dry_run and created > 0:
        print("----------------------------------------\n")
        print(f"{CYAN}Aktualisiere WGDashboard Peers...{NC}\n")
        print(f"{YELLOW}HINWEIS: WGDashboard muss zuerst neu gestartet werden,{NC}")
        print(f"{YELLOW}damit es die neuen Konfigs erkennt!{NC}\n")
        restart_choice = input("WGDashboard jetzt neustarten? (j/N): ").strip()
        if restart_choice.lower().startswith("j"):
            print("Starte WGDashboard neu...")
            restart_service(args.dashboard_service, "restart")
            print("Prüfe Dienst-Status...")
            if not ensure_service_active(args.dashboard_service, timeout=15, interval=1):
                print(f"{RED}Fehler: {args.dashboard_service} läuft nach Restart nicht.{NC}")
                sys.exit(1)
            print(f"{GREEN}Dienst aktiv.{NC}")
            time.sleep(2)

        print("\nAktualisiere Peer-Einstellungen (alle Peers je Config)...\n")

        api_success = api_failed = 0
        for (config_name, _interface_pub, peers_for_conf) in summary:
            if not peers_for_conf:
                continue
            print(f"  {config_name}: ", end="", flush=True)
            time.sleep(3)
            if not start_interface(config_name):
                print(f"{RED}Interface-Start fehlgeschlagen{NC}")
                api_failed += len(peers_for_conf)
                continue

            time.sleep(1)
            for peer in peers_for_conf:
                peer_name = peer.get("name") or args.peer_name
                ok = update_wgdashboard_peer(
                    args.dashboard_url,
                    api_key,
                    config_name,
                    peer["public_key"],
                    peer["private_key"],
                    peer_name,
                    args.peer_dns,
                    peer["allowed_ips"],
                    args.endpoint_allowed_ips,
                    args.peer_mtu,
                    args.peer_keepalive,
                    args.server_endpoint,
                )
                if ok:
                    print(f"{GREEN}[{peer_name}] OK{NC} ", end="", flush=True)
                    api_success += 1
                else:
                    print(f"{YELLOW}[{peer_name}] FAIL{NC} ", end="", flush=True)
                    api_failed += 1
            stop_interface(config_name)
            print("")

        print(f"\nAPI-Updates: {api_success} erfolgreich, {api_failed} fehlgeschlagen")

    # Zusammenfassung
    print("\n========================================")
    print(" Zusammenfassung")
    print("========================================\n")
    print(f"  Gesamt:        {total}")
    print(f"  Erstellt:      {GREEN}{created}{NC}")
    print(f"  Übersprungen:  {YELLOW}{skipped}{NC}")
    print(f"  Fehler:        {RED}{errors}{NC}\n")

    if summary:
        print("========================================")
        print(" Generierte Schlüssel")
        print("========================================\n")
        for (config_name, interface_pub, peers_for_conf) in summary:
            print(f"# {config_name}")
            print(f"#   Interface-PubKey: {interface_pub}")
            for peer in peers_for_conf:
                print(f"#   Peer ({peer.get('name','')}):")
                print(f"#     PublicKey:  {peer['public_key']}")
                print(f"#     PrivateKey: {peer['private_key']}")
                print(f"#     AllowedIPs: {peer['allowed_ips']}")
                if peer.get("endpoint"):
                    print(f"#     Endpoint:   {peer['endpoint']}")
                if peer.get("keepalive"):
                    print(f"#     Keepalive:  {peer['keepalive']}")
            print("")

    if args.dry_run:
        print(f"{YELLOW}DRY-RUN abgeschlossen. Keine Dateien wurden erstellt.{NC}")
    else:
        print(f"{GREEN}Fertig!{NC}")


if __name__ == "__main__":
    try:
        check_dependencies()
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen.")

