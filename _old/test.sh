# WGDashboard stoppen
sudo systemctl stop wg-dashboard

# Alle APW-Tabellen komplett leeren
for table in $(sqlite3 /home/wzf-adm/WGDashboard/src/db/wgdashboard.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'APW%'"); do
  sqlite3 /home/wzf-adm/WGDashboard/src/db/wgdashboard.db "DELETE FROM \"$table\""
  echo "$table geleert"
done

# WGDashboard wieder starten
sudo systemctl start wg-dashboard
