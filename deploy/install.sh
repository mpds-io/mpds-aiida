#!/bin/bash
set -euo pipefail

#================== GENERAL ==================

PG_VERSION="17.9" # NB subject to update
PG_SOURCE_ADDR=https://ftp.postgresql.org/pub/source/v$PG_VERSION/postgresql-$PG_VERSION.tar.gz

SETTINGS=(
postgresql.conf
supervisord.conf
yascheduler.conf
sysctl.conf
aiida_setup.sh
)

for ((i=0; i<${#SETTINGS[@]}; i++)); do
    if [ ! -f $(dirname $0)/${SETTINGS[i]} ]; then
    echo "${SETTINGS[i]} does not exist" ; exit 1
    fi
done

apt-get -y update && apt-get -y upgrade
update-alternatives --install /usr/bin/python python /usr/bin/python3 1

apt-get install -y \
    build-essential \
    rabbitmq-server \
    p7zip-full \
    git \
    swig \
    libicu-dev \
    flex \
    bison \
    pkg-config \
    zlib1g-dev \
    libreadline6-dev \
    libboost-all-dev \
    libopenblas-dev \
    libblas-dev \
    libffi-dev \
    liblapack-dev \
    supervisor \
    python3-dev \
    python3-pip \
;

update-rc.d supervisor defaults
update-rc.d supervisor enable

echo "set mouse-=a" > ~/.vimrc
#rm /root/.netrc

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
su postgres -c "/data/pg/bin/createdb aiida"

chown -R postgres:postgres /data/pg
cd ..
cp $(dirname $0)/postgresql.conf /data/pg/db/

#================== AiiDA ==================

mkdir /etc/yascheduler/
cp $(dirname $0)/yascheduler.conf /etc/yascheduler/
cp $(dirname $0)/supervisord.conf /etc/supervisor/
cat $(dirname $0)/sysctl.conf >> /etc/sysctl.conf

pip install --break-system-packages git+https://github.com/tilde-lab/aiida-crystal-dft
pip install --break-system-packages git+https://github.com/tilde-lab/yascheduler
pip install --break-system-packages git+https://github.com/mpds-io/dft_organizer
pip install --break-system-packages git+https://github.com/mpds-io/aiida-mpds-monitor

git clone https://github.com/mpds-io/mpds-aiida /data/mpds-aiida
pip install --break-system-packages /data/mpds-aiida/
reentry scan
cd /data/mpds-aiida/

cat /dev/zero | ssh-keygen -q -N ""
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys
