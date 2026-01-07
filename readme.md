# ENG:

# WGD-masscreate
A compact CLI tool for creating and deleting WireGuard interfaces using WGDashboard.
This tool is particularly suited for IoT remote maintenance solutions where each station should be accessed in the same way (same IP range, etc.).
WARNING! The created interfaces are all identical from a network perspective, meaning only one can be active at a time (e.g., the specific facility being accessed). This saves IPs in the WG-WAN and prevents cross-communication between interfaces of the same type (e.g., facilities). The configuration of remote access interfaces must accordingly have a different WG server IP, and the endpoint IPs must be adjusted.
Prerequisites

config.ini in the working directory (or via --config), section [defaults] with all keys.
Binaries: wg, wg-quick, ip, systemctl.
Access to WGDashboard (API key) and SQLite DB.

## Usage (Examples)

Review/adjust configuration in config.ini.
Generate:

   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 -k <API_KEY>
Interactive input (prefix, start, end, API key) is available if not set via CLI.

Optional: Dry-run without writing:

   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 -k <API_KEY> --dry-run

Delete only (interfaces, routes, .conf files, DB tables in range):

   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 --delete-only
Additional Peers per Interface

Any number of static peers can be defined in the ini as sections [peer.<name>], e.g.:

  [peer.client1]
  public_key = AbCd...
  allowed_ips = 10.128.244.50/32, 192.168.50.0/24
  endpoint = gw.example.com:51820      ; optional
  keepalive = 25                       ; optional

Each defined peer section is included as an additional [Peer] block in every generated .conf.

## Options

-p, --prefix PREFIX — Prefix for filenames, e.g., APW
-s, --start NUM — Start number (supports leading zeros in input)
-e, --end NUM — End number
-k, --api-key KEY — WGDashboard API key
-d, --dir PATH — Target directory for .conf (default from ini)
-a, --address CIDR — Interface address
-l, --port PORT — ListenPort
-i, --allowed-ips LIST — Peer AllowedIPs in server config
--peer-name NAME — Peer name in WGDashboard
--endpoint HOST:PORT — Server endpoint for client config
--delete-existing — Delete existing .conf files in target (except those starting with _)
-n, --dry-run — Display only, don't write anything
--dashboard-url URL — WGDashboard base URL
--dashboard-db PATH — Path to WGDashboard SQLite DB
--dashboard-service NAME — Service name (systemctl) for WGDashboard
--peer-dns DNS — DNS for client
--peer-mtu MTU — MTU for client
--peer-keepalive SEC — PersistentKeepalive for client
--endpoint-allowed-ips LIST — AllowedIPs in client config
--config PATH — Path to ini file
--delete-only — Delete only in specified range: stop/delete wg interface, remove associated routes (from --allowed-ips), delete .conf, clear matching DB tables (prefix-based)

## Notes

The ini file is mandatory; missing keys will cause the tool to abort.
Numbering supports leading zeros, e.g., -s 001 -e 010 generates 001 … 010.
API updates require WGDashboard to be running; the tool can restart the service and checks its status.

## Security

Private keys are generated locally; .conf files are set to mode 0600.

# DEU:

# WGD-masscreate

Kurzes CLI-Tool zum Erzeugen und Löschen von WireGuard-Interfaces mit WGDashboard.
Das Tool eignet sich insbesondere für IoT Fernwartungslösungen, bei denen jede Station auf dem gleichen Weg (gleicher IP-Bereich etc) angesprochen werden soll.

ACHTUNG!: Die erstellte Interfaces sind netzwerkseitig alle gleich, d.h. es kann nur eines aktiviert werden (bspw. die betroffene Anlage, auf die zugegriffen werden soll). Das spart IPs im WG-WAN und unterbindet Querkommunikation zwischen Interfaces gleicher Art (zB. Anlagen). Die Konfig der Ferzugriffs-Interfaces muss entsprechend eine andere WG-Server IP haben, die Endpoint-IPs müssen angepasst werden.

## Voraussetzungen
- `config.ini` im Arbeitsverzeichnis (oder via `--config`), Abschnitt `[defaults]` mit allen Keys.
- Binaries: `wg`, `wg-quick`, `ip`, `systemctl`.
- Zugriff auf WGDashboard (API-Key) und SQLite-DB.

## Nutzung (Beispiele)
1. Konfiguration prüfen/anpassen in `config.ini`.

2. Generieren:
   ```
   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 -k <API_KEY>
   ```
   Interaktive Eingaben (Prefix, Start, Ende, API-Key) sind möglich, wenn nicht per CLI gesetzt.

3. Optional: Dry-Run ohne Schreiben:
   ```
   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 -k <API_KEY> --dry-run
   ```

4. Nur löschen (Interfaces, Routen, .conf, DB-Tabellen im Bereich):
   ```
   python3 masscreate.py --config config.ini -p APW -s 1 -e 10 --delete-only
   ```

## Zusätzliche Peers pro Interface
- Beliebig viele statische Peers können in der ini als Sektionen ` [peer.<name>] ` angelegt werden, z.B.:
  ```
  [peer.client1]
  public_key = AbCd...
  allowed_ips = 10.128.244.50/32, 192.168.50.0/24
  endpoint = gw.example.com:51820      ; optional
  keepalive = 25                       ; optional
  ```
- Jede definierte Peer-Sektion wird als zusätzlicher `[Peer]`-Block in jede generierte `.conf` übernommen.

## Optionen
- `-p, --prefix PREFIX` Präfix für Dateinamen, z.B. `APW`
- `-s, --start NUM` Startnummer (unterstützt führende Nullen in der Eingabe)
- `-e, --end NUM` Endnummer
- `-k, --api-key KEY` WGDashboard API-Key
- `-d, --dir PATH` Zielverzeichnis für `.conf` (Default aus ini)
- `-a, --address CIDR` Interface-Adresse
- `-l, --port PORT` ListenPort
- `-i, --allowed-ips LIST` Peer AllowedIPs in der Server-Konfig
- `--peer-name NAME` Peer-Name in WGDashboard
- `--endpoint HOST:PORT` Server-Endpoint für Client-Konfig
- `--delete-existing` Vorhandene `.conf` im Ziel löschen (außer mit `_` beginnend)
- `-n, --dry-run` Nur anzeigen, nichts schreiben
- `--dashboard-url URL` WGDashboard Basis-URL
- `--dashboard-db PATH` Pfad zur WGDashboard SQLite DB
- `--dashboard-service NAME` Service-Name (systemctl) für WGDashboard
- `--peer-dns DNS` DNS für Client
- `--peer-mtu MTU` MTU für Client
- `--peer-keepalive SEC` PersistentKeepalive für Client
- `--endpoint-allowed-ips LIST` AllowedIPs in der Client-Konfig
- `--config PATH` Pfad zur ini-Datei
- `--delete-only` Nur löschen im angegebenen Bereich: wg-Interface stoppen/löschen, zugehörige Routen entfernen (aus `--allowed-ips`), `.conf` löschen, passende DB-Tabellen (präfixbasierend) leeren

## Hinweise
- Die ini ist Pflicht; fehlen Keys, bricht das Tool ab.
- Numerierung unterstützt führende Nullen, z.B. `-s 001 -e 010` erzeugt `001` … `010`.
- API-Updates erfordern laufendes WGDashboard; das Tool kann den Dienst neu starten und prüft den Status.

## Sicherheit
- Private Keys werden lokal erzeugt; `.conf`-Dateien erhalten 0600.

