# WGD-masscreate

Kurzes CLI-Tool zum Erzeugen und Löschen von WireGuard-Interfaces mit WGDashboard.
Das Tool eignet sich insbesondere für IoT Fernwartungslösungen, bei denen jede Station auf dem gleichen Weg (gleicher IP-Bereich etc) angesprochen werden soll.

ACHTUNG!: Die erstellte Interfaces sind netzwerkseitig alle gleich, d.h. es kann nur eines aktiviert werden (bspw. die betroffene Anlage,a uf die zugegriffen werden soll). Das spart IPs im WG-WAN und ist unterbindet Querkommunikation zwischen Interfaces gleicher Art (zB. Anlagen). Die Konfig der Ferzugriffs-Interfaces muss entsprechend eine andere WG-Server IP haben, die Endpoint-IPs müssen angepasst werden.

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

