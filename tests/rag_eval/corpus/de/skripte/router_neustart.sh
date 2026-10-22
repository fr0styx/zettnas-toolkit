#!/bin/sh
# Startet die Fritzbox neu, wenn das Internet länger als 5 Minuten weg ist.
ZIEL=1.1.1.1
FEHLER=0
while true; do
  if ping -c1 -W2 "$ZIEL" >/dev/null 2>&1; then
    FEHLER=0
  else
    FEHLER=$((FEHLER + 1))
  fi
  if [ "$FEHLER" -ge 10 ]; then
    logger "Internet weg, starte Router neu"
    curl -s "http://fritz.box:49000/igdupnp/control/WANIPConn1" >/dev/null
    FEHLER=0
  fi
  sleep 30
done
