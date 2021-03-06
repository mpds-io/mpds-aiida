#!/bin/bash

#================== GENERAL ==================

PG_SOURCE_ADDR=https://ftp.postgresql.org/pub/source/v13.1/postgresql-13.1.tar.gz # NB KEEP UPDATED
PG_VERSION="13.1" # NB KEEP UPDATED

SETTINGS=(
postgresql.conf
supervisord.conf
sysctl.conf
)

for ((i=0; i<${#SETTINGS[@]}; i++)); do
    if [ ! -f $(dirname $0)/${SETTINGS[i]} ]; then
    echo "${SETTINGS[i]} does not exist" ; exit 1
    fi
done

apt-get -y update && apt-get -y upgrade
apt-get -y install build-essential libatlas-base-dev libopenblas-dev libblas-dev libffi-dev libreadline6-dev zlib1g-dev liblapack-dev supervisor python3-dev python3-pip python3-numpy python3-scipy python3-matplotlib p7zip-full git swig python3-setuptools rabbitmq-server pkg-config

update-rc.d supervisor defaults
update-rc.d supervisor enable

echo "set mouse-=a" > ~/.vimrc
rm /root/.netrc

#================== POSTGRES ==================

useradd postgres
mkdir -p /data/pg
mkdir /data/pg/db
chown -R postgres:postgres /data/pg

wget $PG_SOURCE_ADDR
wget $PG_SOURCE_ADDR.md5
GOT_SUM=`md5sum *.tar.gz | cut -d" " -f1`
HAVE_SUM=`cut -d' ' -f1 < *.tar.gz.md5`
if [ "$GOT_SUM" != "$HAVE_SUM" ]; then
    echo "INVALID CHECKSUM"
    exit 1
fi

tar xvf postgresql-$PG_VERSION.tar.gz
cd postgresql-$PG_VERSION
./configure --prefix=/data/pg
make && make install
su postgres -c "/data/pg/bin/initdb -D /data/pg/db"
su postgres -c "/data/pg/bin/pg_ctl -D /data/pg/db -l /tmp/logfile start"
su postgres -c "/data/pg/bin/createdb aiidadb"

chown -R postgres:postgres /data/pg
cd ..
cp $(dirname $0)/postgresql.conf /data/pg/db/

#================== GENERAL#2 ==================

cp $(dirname $0)/supervisord.conf /etc/supervisor/
cat $(dirname $0)/sysctl.conf >> /etc/sysctl.conf

shutdown -r now
systemctl reboot # if previous fails