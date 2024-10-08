#!/bin/bash

#/*
#* nextcloud docker-compose script
#* Copyright (C) 2024 Antoine DELAPORTE
#*
#* This program is free software: you can redistribute it and/or modify
#* it under the terms of the GNU General Public License as published by
#* the Free Software Foundation, either version 3 of the License, or
#* (at your option) any later version.
#*
#* This program is distributed in the hope that it will be useful,
#* but WITHOUT ANY WARRANTY; without even the implied warranty of
#* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#* GNU General Public License for more details.
#*
#* You should have received a copy of the GNU General Public License
#* along with this program.  If not, see <http://www.gnu.org/licenses/>.
#*/

#set -x

chmod 777 /tmp
chmod o+t /tmp

# Répertoire contenant les dumps
dump_dir="/var/lib/mysqldump/"

# Nombre de fichiers à conserver par base
keep=4

# Heure cible (au format HH:MM:SS)
target_time="21:00:00"

# Obtenir l'heure actuelle en secondes depuis minuit
current_seconds=$(date +%s)

# Obtenir la date actuelle et remplacer l'heure par l'heure cible
target_seconds=$(date -d "$(date +%Y-%m-%d) $target_time" +%s)

# Calculer la différence de temps (en secondes)
sleep_seconds=$((target_seconds - current_seconds))

# Si l'heure cible est dans le futur, attendre jusqu'à cette heure
if [[ $sleep_seconds -gt 0 ]]; then
    echo "Attente jusqu'à $target_time... soit $sleep_seconds"
    sleep $sleep_seconds
else
    echo "L'heure spécifiée est déjà passée pour aujourd'hui."
fi

# Le script continue ici après l'attente
echo "Il est maintenant $target_time."


MYSQLDUMP_OPTS=""

echo $0

if [ $0 = "/db-dump" ]; then
    EP=exit
    CMD=0
    echo db is the host and Im fine
    echo Waiting for db
    while ! >/dev/tcp/db/3306 2>/dev/null;do
       echo Waiting for db init
       sleep 10
       done
    echo Waiting for nc
    while ! >/dev/tcp/nextcloud/80 2>/dev/null;do
       echo Waiting for nc init
       sleep 10
       done

    echo Dumping
    /usr/bin/mysql -h db -p$MYSQL_ROOT_PASSWORD -e 'show databases\G' | grep -v '^\*' | cut -d' ' -f2 | while read db
        do
        DUNA=`date +$db-%Y%m%d%H%M%S.sql.gz`
        echo Dumping $db filename $DUNA
        /usr/bin/mysqldump $MYSQLDUMP_OPTS -h db -p$MYSQL_ROOT_PASSWORD $db | gzip -9 >$dump_dir/$DUNA
        ln -sf $DUNA $dump_dir/$db.sql.gz
        done
    fi

# Lister les bases (en supposant que chaque base a un préfixe unique pour ses dumps)
for base in $(ls "$dump_dir" | grep -o '^[^_]*' | sort -u); do
    # Lister les fichiers pour cette base, les trier par date, et en conserver les 4 plus récents
    files=$(ls -t "$dump_dir/$base"* 2>/dev/null)
    
    # Vérifier s'il y a plus de 4 fichiers
    if [[ $(echo "$files" | wc -l) -gt $keep ]]; then
        # Supprimer les fichiers plus anciens que les 4 plus récents
        echo "$files" | tail -n +$(($keep + 1)) | xargs rm -f
        echo "Conservation des 4 derniers dumps pour la base '$base'. Suppression des anciens."
    else
        echo "Pas assez de fichiers pour la base '$base' à supprimer."
    fi
done
