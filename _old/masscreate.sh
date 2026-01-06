#!/bin/bash
#
# WireGuard Massenkonfigurations-Generator mit WGDashboard-Integration
# Erstellt WireGuard-Konfigurationen mit Schlüsselpaaren und registriert sie in WGDashboard
#

set -e

# Farben für Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Standardwerte aus Beispielkonfiguration
DEFAULT_ADDRESS="10.128.244.1/32"
DEFAULT_LISTEN_PORT="51800"
DEFAULT_PEER_ALLOWED_IPS="10.128.244.10/32, 192.168.0.0/25"
DEFAULT_TARGET_DIR="/etc/wireguard"
DEFAULT_PEER_NAME="Router"
DEFAULT_SERVER_ENDPOINT="10.128.128.29:51800"
DEFAULT_PEER_DNS="1.1.1.1"
DEFAULT_PEER_MTU="1420"
DEFAULT_PEER_KEEPALIVE="21"
# Für Client-Konfig: AllowedIPs nur das interne Netz (nicht die Peer-IP)
DEFAULT_ENDPOINT_ALLOWED_IPS="192.168.0.0/25"

# WGDashboard
WGDASHBOARD_URL="http://localhost:10086"
API_KEY=""

# Zähler
TOTAL=0
CREATED=0
SKIPPED=0
ERRORS=0

increment_total() { TOTAL=$((TOTAL + 1)); }
increment_created() { CREATED=$((CREATED + 1)); }
increment_skipped() { SKIPPED=$((SKIPPED + 1)); }
increment_errors() { ERRORS=$((ERRORS + 1)); }

show_help() {
    echo "Verwendung: $0 [OPTIONEN]"
    echo ""
    echo "Erstellt WireGuard-Konfigurationsdateien mit Schlüsselpaaren und"
    echo "registriert die Peer-PrivateKeys in WGDashboard."
    echo ""
    echo "Optionen:"
    echo "  -p, --prefix PREFIX      Präfix für Dateinamen (z.B. 'APW')"
    echo "  -s, --start NUM          Startnummer (z.B. 1)"
    echo "  -e, --end NUM            Endnummer (z.B. 100)"
    echo "  -k, --api-key KEY        WGDashboard API-Key"
    echo "  -d, --dir VERZEICHNIS    Zielverzeichnis (Standard: $DEFAULT_TARGET_DIR)"
    echo "  -a, --address IP/MASK    Interface-Adresse (Standard: $DEFAULT_ADDRESS)"
    echo "  -l, --port PORT          ListenPort (Standard: $DEFAULT_LISTEN_PORT)"
    echo "  -i, --allowed-ips IPS    Peer AllowedIPs in Server-Konfig (Standard: $DEFAULT_PEER_ALLOWED_IPS)"
    echo "  --peer-name NAME         Peer-Name in WGDashboard (Standard: $DEFAULT_PEER_NAME)"
    echo "  --endpoint HOST:PORT     Server-Endpoint für Client-Konfig (Standard: $DEFAULT_SERVER_ENDPOINT)"
    echo "  --delete-existing        Bestehende Konfigs löschen (außer _*)"
    echo "  -n, --dry-run            Nur anzeigen, nichts schreiben"
    echo "  -h, --help               Diese Hilfe anzeigen"
    echo ""
    echo "Beispiel:"
    echo "  $0 -p APW -s 1 -e 100 -k mein_api_key"
    echo "  $0 --prefix Anlage --start 1 --end 50 --dry-run"
    echo "  $0 --delete-existing -p APW -s 1 -e 100 -k api_key"
}

check_dependencies() {
    local missing=()
    
    if ! command -v wg &> /dev/null; then
        missing+=("wireguard-tools")
    fi
    
    if ! command -v curl &> /dev/null; then
        missing+=("curl")
    fi
    
    if ! command -v jq &> /dev/null; then
        missing+=("jq")
    fi
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Fehler: Fehlende Abhängigkeiten: ${missing[*]}${NC}"
        echo "Installation: apt install ${missing[*]}"
        exit 1
    fi
}

delete_existing_configs() {
    echo ""
    echo -e "${YELLOW}Lösche bestehende Konfigurationen...${NC}"
    
    local count=0
    
    for conf_file in "$TARGET_DIR"/*.conf; do
        # Prüfen ob Dateien existieren
        [[ -e "$conf_file" ]] || continue
        
        local conf_name=$(basename "$conf_file" .conf)
        
        # Überspringe Dateien die mit _ beginnen
        if [[ "$conf_name" == _* ]]; then
            echo -e "  ${CYAN}Überspringe:${NC} $conf_file (beginnt mit _)"
            continue
        fi
        
        if [[ "$DRY_RUN" == true ]]; then
            echo -e "  ${YELLOW}[DRY-RUN]${NC} Würde löschen: $conf_file"
        else
            rm -f "$conf_file"
            echo -e "  ${GREEN}Gelöscht:${NC} $conf_file"
        fi
        count=$((count + 1))
    done
    
    echo "  $count Konfiguration(en) verarbeitet."
    echo ""
}

create_config() {
    local name="$1"
    local interface_privkey="$2"
    local peer_pubkey="$3"
    
    cat << EOF
[Interface]
Address = $ADDRESS
SaveConfig = true
PreUp =
PostUp =
PreDown =
PostDown =
ListenPort = $LISTEN_PORT
PrivateKey = $interface_privkey

[Peer]
PublicKey = $peer_pubkey
AllowedIPs = $PEER_ALLOWED_IPS
EOF
}

start_wireguard_interface() {
    local config_name="$1"
    
    # Prüfen ob Interface bereits läuft
    if ip link show "$config_name" &>/dev/null; then
        return 0
    fi
    
    # Interface starten
    wg-quick up "$config_name" &>/dev/null
    return $?
}

stop_wireguard_interface() {
    local config_name="$1"
    
    # Prüfen ob Interface läuft
    if ip link show "$config_name" &>/dev/null; then
        wg-quick down "$config_name" &>/dev/null || ip link delete "$config_name" &>/dev/null
    fi
}

update_wgdashboard_peer() {
    local config_name="$1"
    local peer_pubkey="$2"
    local peer_privkey="$3"
    local peer_name="$4"
    
    # API erwartet ALLE Felder im JSON-Body
    # Diese Werte bestimmen die Client-Konfig die WGDashboard generiert:
    # - DNS: DNS-Server für Client
    # - allowed_ip: AllowedIPs in SERVER-Konfig (was der Server vom Client akzeptiert)
    # - endpoint_allowed_ip: AllowedIPs in CLIENT-Konfig (was der Client durch den Tunnel schickt)
    # - mtu: MTU für Client
    # - keepalive: PersistentKeepalive für Client
    # - remote_endpoint: Endpoint in CLIENT-Konfig (Server-Adresse)
    local response=$(curl -s -X POST \
        -H "wg-dashboard-apikey: $API_KEY" \
        -H "Content-Type: application/json" \
        -d "{
            \"id\": \"$peer_pubkey\",
            \"name\": \"$peer_name\",
            \"private_key\": \"$peer_privkey\",
            \"DNS\": \"$PEER_DNS\",
            \"allowed_ip\": \"$PEER_ALLOWED_IPS\",
            \"endpoint_allowed_ip\": \"$ENDPOINT_ALLOWED_IPS\",
            \"preshared_key\": \"\",
            \"mtu\": $PEER_MTU,
            \"keepalive\": $PEER_KEEPALIVE,
            \"remote_endpoint\": \"$SERVER_ENDPOINT\"
        }" \
        "$WGDASHBOARD_URL/api/updatePeerSettings/$config_name" 2>/dev/null || echo "")
    
    # Prüfe ob erfolgreich
    if echo "$response" | jq -e '.status == true' &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Standardwerte setzen
PREFIX=""
START=""
END=""
TARGET_DIR="$DEFAULT_TARGET_DIR"
ADDRESS="$DEFAULT_ADDRESS"
LISTEN_PORT="$DEFAULT_LISTEN_PORT"
PEER_ALLOWED_IPS="$DEFAULT_PEER_ALLOWED_IPS"
PEER_NAME="$DEFAULT_PEER_NAME"
SERVER_ENDPOINT="$DEFAULT_SERVER_ENDPOINT"
PEER_DNS="$DEFAULT_PEER_DNS"
PEER_MTU="$DEFAULT_PEER_MTU"
PEER_KEEPALIVE="$DEFAULT_PEER_KEEPALIVE"
ENDPOINT_ALLOWED_IPS="$DEFAULT_ENDPOINT_ALLOWED_IPS"
DELETE_EXISTING=false
DRY_RUN=false

# Parameter parsen
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--prefix)
            PREFIX="$2"
            shift 2
            ;;
        -s|--start)
            START="$2"
            shift 2
            ;;
        -e|--end)
            END="$2"
            shift 2
            ;;
        -k|--api-key)
            API_KEY="$2"
            shift 2
            ;;
        -d|--dir)
            TARGET_DIR="$2"
            shift 2
            ;;
        -a|--address)
            ADDRESS="$2"
            shift 2
            ;;
        -l|--port)
            LISTEN_PORT="$2"
            shift 2
            ;;
        -i|--allowed-ips)
            PEER_ALLOWED_IPS="$2"
            shift 2
            ;;
        --peer-name)
            PEER_NAME="$2"
            shift 2
            ;;
        --endpoint)
            SERVER_ENDPOINT="$2"
            shift 2
            ;;
        --delete-existing)
            DELETE_EXISTING=true
            shift
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unbekannte Option: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# Abhängigkeiten prüfen
check_dependencies

# Interaktive Eingabe falls Parameter fehlen
if [[ -z "$PREFIX" ]]; then
    read -p "Präfix eingeben (z.B. AA): " PREFIX
fi

if [[ -z "$START" ]]; then
    read -p "Startnummer eingeben (z.B. 1): " START
fi

if [[ -z "$END" ]]; then
    read -p "Endnummer eingeben (z.B. 10): " END
fi

if [[ -z "$API_KEY" ]]; then
    read -sp "WGDashboard API-Key eingeben: " API_KEY
    echo ""
fi

# Validierung
if [[ -z "$PREFIX" ]] || [[ -z "$START" ]] || [[ -z "$END" ]]; then
    echo -e "${RED}Fehler: Präfix, Start- und Endnummer müssen angegeben werden!${NC}"
    exit 1
fi

if ! [[ "$START" =~ ^[0-9]+$ ]] || ! [[ "$END" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}Fehler: Start und Ende müssen Zahlen sein!${NC}"
    exit 1
fi

if [[ "$START" -gt "$END" ]]; then
    echo -e "${RED}Fehler: Startnummer muss kleiner oder gleich Endnummer sein!${NC}"
    exit 1
fi

if [[ -z "$API_KEY" ]]; then
    echo -e "${RED}Fehler: API-Key erforderlich!${NC}"
    exit 1
fi

# Ziffernbreite ermitteln (für führende Nullen)
DIGITS=${#END}

# Header
echo ""
echo "========================================"
echo " WireGuard Konfigurations-Generator"
echo "========================================"
echo ""
echo "Einstellungen:"
echo "  Präfix:        $PREFIX"
echo "  Bereich:       $START - $END"
echo "  Ziel:          $TARGET_DIR"
echo "  Address:       $ADDRESS"
echo "  ListenPort:    $LISTEN_PORT"
echo "  Peer-Name:     $PEER_NAME"
echo "  AllowedIPs:    $PEER_ALLOWED_IPS"
echo "  Endpoint:      $SERVER_ENDPOINT"
echo "  Dashboard:     $WGDASHBOARD_URL"
if [[ "$DELETE_EXISTING" == true ]]; then
    echo -e "  ${YELLOW}Lösche bestehende Konfigs!${NC}"
fi
if [[ "$DRY_RUN" == true ]]; then
    echo -e "  ${YELLOW}Modus: DRY-RUN${NC}"
fi
echo ""

# API-Verbindung testen
echo -n "Teste API-Verbindung... "
API_TEST=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "wg-dashboard-apikey: $API_KEY" \
    "$WGDASHBOARD_URL/api/handshake" 2>/dev/null || echo "000")

if [[ "$API_TEST" != "200" ]]; then
    echo -e "${RED}Fehlgeschlagen (HTTP $API_TEST)${NC}"
    echo "Bitte API-Key und URL prüfen."
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Zielverzeichnis prüfen/erstellen
if [[ "$DRY_RUN" == false ]]; then
    if [[ ! -d "$TARGET_DIR" ]]; then
        echo -e "${YELLOW}Zielverzeichnis existiert nicht. Erstelle: $TARGET_DIR${NC}"
        mkdir -p "$TARGET_DIR"
    fi
    
    if [[ ! -w "$TARGET_DIR" ]]; then
        echo -e "${RED}Fehler: Keine Schreibrechte für $TARGET_DIR${NC}"
        echo "Tipp: Script mit sudo ausführen"
        exit 1
    fi
fi

# Bestehende Konfigs löschen falls gewünscht
if [[ "$DELETE_EXISTING" == true ]]; then
    delete_existing_configs
fi

echo "----------------------------------------"
echo ""

# Arrays für Zusammenfassung
declare -a SUMMARY

# Konfigurationen erstellen
for ((i=START; i<=END; i++)); do
    increment_total
    
    # Nummer mit führenden Nullen formatieren
    NUM=$(printf "%0${DIGITS}d" "$i")
    CONFIG_NAME="${PREFIX}${NUM}"
    FILENAME="${CONFIG_NAME}.conf"
    FILEPATH="${TARGET_DIR}/${FILENAME}"
    
    echo -e "${CYAN}[$CONFIG_NAME]${NC}"
    
    # Prüfen ob Datei bereits existiert
    if [[ -f "$FILEPATH" ]] && [[ "$DELETE_EXISTING" == false ]]; then
        echo -e "  ${YELLOW}Existiert bereits, überspringe${NC}"
        increment_skipped
        echo ""
        continue
    fi
    
    # Schlüsselpaare generieren
    # 1. Interface-Schlüsselpaar
    INTERFACE_PRIVKEY=$(wg genkey)
    INTERFACE_PUBKEY=$(echo "$INTERFACE_PRIVKEY" | wg pubkey)
    
    # 2. Peer (Router) Schlüsselpaar
    PEER_PRIVKEY=$(wg genkey)
    PEER_PUBKEY=$(echo "$PEER_PRIVKEY" | wg pubkey)
    
    echo "  Interface-PrivKey: ${INTERFACE_PRIVKEY:0:15}..."
    echo "  Interface-PubKey:  ${INTERFACE_PUBKEY:0:15}..."
    echo "  Peer-PrivKey:      ${PEER_PRIVKEY:0:15}..."
    echo "  Peer-PubKey:       ${PEER_PUBKEY:0:15}..."
    
    # Zusammenfassung speichern
    SUMMARY+=("$CONFIG_NAME|$INTERFACE_PUBKEY|$PEER_PRIVKEY|$PEER_PUBKEY")
    
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "  ${YELLOW}[DRY-RUN] Würde erstellen: $FILEPATH${NC}"
        increment_created
    else
        # Konfiguration schreiben
        create_config "$CONFIG_NAME" "$INTERFACE_PRIVKEY" "$PEER_PUBKEY" > "$FILEPATH"
        chmod 600 "$FILEPATH"
        echo -e "  ${GREEN}Konfig erstellt: $FILEPATH${NC}"
        increment_created
    fi
    
    echo ""
done

# WGDashboard neu laden und Peers aktualisieren
if [[ "$DRY_RUN" == false ]] && [[ $CREATED -gt 0 ]]; then
    echo "----------------------------------------"
    echo ""
    echo -e "${CYAN}Aktualisiere WGDashboard Peers...${NC}"
    echo ""
    echo -e "${YELLOW}HINWEIS: WGDashboard muss zuerst neu gestartet werden,${NC}"
    echo -e "${YELLOW}damit es die neuen Konfigs erkennt!${NC}"
    echo ""
    read -p "WGDashboard jetzt neustarten? (j/N): " RESTART_DASHBOARD
    
    if [[ "$RESTART_DASHBOARD" =~ ^[jJyY]$ ]]; then
        echo "Starte WGDashboard neu..."
        systemctl restart wg-dashboard 2>/dev/null || echo -e "${YELLOW}Konnte wg-dashboard nicht neustarten${NC}"
        echo "Warte 5 Sekunden..."
        sleep 5
    fi
    
    echo ""
    echo "Aktualisiere Peer-Einstellungen..."
    echo -e "${YELLOW}(Interface wird temporär aktiviert für API-Update)${NC}"
    echo ""
    
    api_success=0
    api_failed=0
    
    for entry in "${SUMMARY[@]}"; do
        CONFIG_NAME=$(echo "$entry" | cut -d'|' -f1)
        PEER_PRIVKEY=$(echo "$entry" | cut -d'|' -f3)
        PEER_PUBKEY=$(echo "$entry" | cut -d'|' -f4)
        
        echo -n "  $CONFIG_NAME: "
        
        # 3 Sekunden warten vor Interface-Start
        sleep 3
        
        # Interface muss aktiv sein für API-Update
        if ! start_wireguard_interface "$CONFIG_NAME"; then
            echo -e "${RED}Interface-Start fehlgeschlagen${NC}"
            api_failed=$((api_failed + 1))
            continue
        fi
        
        # Kurz warten damit WGDashboard das Interface erkennt
        sleep 1
        
        if update_wgdashboard_peer "$CONFIG_NAME" "$PEER_PUBKEY" "$PEER_PRIVKEY" "$PEER_NAME"; then
            echo -e "${GREEN}OK${NC}"
            api_success=$((api_success + 1))
        else
            echo -e "${YELLOW}API-Update fehlgeschlagen${NC}"
            api_failed=$((api_failed + 1))
        fi
        
        # Interface wieder stoppen
        stop_wireguard_interface "$CONFIG_NAME"
    done
    
    echo ""
    echo "API-Updates: $api_success erfolgreich, $api_failed fehlgeschlagen"
fi

# Zusammenfassung ausgeben
echo ""
echo "========================================"
echo " Zusammenfassung"
echo "========================================"
echo ""
echo "  Gesamt:        $TOTAL"
echo -e "  Erstellt:      ${GREEN}$CREATED${NC}"
echo -e "  Übersprungen:  ${YELLOW}$SKIPPED${NC}"
echo -e "  Fehler:        ${RED}$ERRORS${NC}"
echo ""

if [[ ${#SUMMARY[@]} -gt 0 ]]; then
    echo "========================================"
    echo " Generierte Schlüssel (für Referenz)"
    echo "========================================"
    echo ""
    echo "# Config | Interface-PubKey | Peer-PrivKey (für Router)"
    echo "# -------------------------------------------------------"
    for entry in "${SUMMARY[@]}"; do
        CONFIG_NAME=$(echo "$entry" | cut -d'|' -f1)
        INTERFACE_PUBKEY=$(echo "$entry" | cut -d'|' -f2)
        PEER_PRIVKEY=$(echo "$entry" | cut -d'|' -f3)
        echo "# $CONFIG_NAME"
        echo "#   Interface-PubKey: $INTERFACE_PUBKEY"
        echo "#   Peer-PrivKey:     $PEER_PRIVKEY"
        echo ""
    done
fi

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}DRY-RUN abgeschlossen. Keine Dateien wurden erstellt.${NC}"
else
    echo -e "${GREEN}Fertig!${NC}"
    echo ""
    if [[ $api_failed -gt 0 ]]; then
        echo -e "${YELLOW}HINWEIS: Bei fehlgeschlagenen API-Updates die Peer-PrivateKeys${NC}"
        echo -e "${YELLOW}manuell in WGDashboard eintragen für Config-Download.${NC}"
    fi
fi
