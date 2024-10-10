#!/bin/bash
# Verify package libblkio
function tests_failed() {
        exit_code="$?"
        echo "Test failed: $1"
        exit "${exit_code}"
}

echo "Deploy ..."
yum install -y wget git meson rust cargo python3-docutils rustfmt || tests_failed "Deployment"

echo "Clean"
mkdir -p /home/libblkio
cd /home/libblkio ;rm * -rf

echo "Search source link ..."
repo_url=`yum repoinfo  --repo system-upgrade-appstream   |grep Repo-baseurl|grep -o http.*`
[ "${repo_url}" == "" ] && tests_failed "Get repo url failed"

source_url="${repo_url}../../source/tree/Packages/"
wget -O index.html ${source_url}  || tests_failed "Get source page ${source_url} failed"

libblkio_package=`cat index.html |grep -m 1 -oP "libblkio-.*?.src.rpm"|head -1`
[ "${libblkio_package}" == "" ] && tests_failed "Search libblkio package failed"

libblkio_url="${source_url}${libblkio_package}"
wget ${libblkio_url} || tests_failed "Download libblkio package failed"

echo "Install source rpm"
rpm -ivh ${libblkio_package} || tests_failed "Install source rpm failed"


mkdir source;cd source
for p in `ls ~/rpmbuild/SOURCES/libblkio-v[0-9]*.bz2`;do
tar xvf $p || tests_failed "Untar source rpm failed"
done
cd `ls -d libblkio*` ||  tests_failed "Can not find  source folder"


echo "Compile ..."
meson setup build || tests_failed "Test suite setup"
meson compile -C build || tests_failed "Test suite compile"

echo "Test virtio-blk-vhost-vdpa"
vdpa dev del blk0
modprobe -r vhost-vdpa vdpa-sim-blk
modprobe -a vhost-vdpa vdpa-sim-blk || tests_failed "vhost-vdpa module load"
vdpa dev add mgmtdev vdpasim_blk name blk0 || tests_failed "vhost-vdpa device create"

meson test -C build --suite virtio-blk-vhost-vdpa || tests_failed "virtio-blk-vhost-vdpa"

vdpa dev del blk0
modprobe -r vhost-vdpa vdpa-sim-blk
