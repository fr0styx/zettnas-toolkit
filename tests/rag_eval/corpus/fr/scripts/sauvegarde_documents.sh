#!/bin/bash
# Copie chaque dimanche les documents administratifs vers le disque externe
SOURCE="/mnt/user/papiers"
CIBLE="/mnt/disks/disque_externe/papiers"
JOURNAL="/var/log/sauvegarde_papiers.log"

if [ ! -d "$CIBLE" ]; then
  echo "$(date) disque externe absent" >> "$JOURNAL"
  exit 1
fi
rsync -a --delete "$SOURCE/" "$CIBLE/"
echo "$(date) sauvegarde terminée" >> "$JOURNAL"
