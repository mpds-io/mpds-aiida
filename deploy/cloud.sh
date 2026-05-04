#!/bin/bash
set -euo pipefail

apt-get -y update && apt-get -y upgrade && apt-get install -y build-essential swig p7zip-full pkg-config libopenblas-dev libblas-dev liblapack-dev cmake libopenblas-dev libxml2-dev build-essential gfortran git libarpack2 libarpack2-dev libxc-dev

wget https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.7.tar.gz
tar xvf openmpi-4.1.7.tar.gz
cd openmpi-4.1.7
./configure
make -j8
make install
cd

ulimit -n 65536

export LD_LIBRARY_PATH=/usr/local/lib
export OMP_NUM_THREADS=1
export OMP_STACKSIZE=16M
export MKL_DEBUG_CPU_TYPE=5
mpirun -V

cd ~/ && export FC=mpifort && export CXX=mpicxx && export CC=mpicc && export LD_LIBRARY_PATH=/usr/local/lib && git clone --depth 1 --branch MaX-R6.2 https://iffgit.fz-juelich.de/fleur/fleur && cd fleur && ./configure.sh && cd build && make -j8
