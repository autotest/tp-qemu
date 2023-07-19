#!/bin/bash
# Verify package libblkio
function tests_failed() {
        exit_code="$?"
        echo "Test failed: $1"
        exit "${exit_code}"
}

echo "Deploy ..."
yum install -y git meson rust cargo python3-docutils rustfmt || tests_failed "Deployment"
rm -rf /home/libblkio
git clone https://gitlab.com/libblkio/libblkio.git /home/libblkio || tests_failed "Git clone"
cd /home/libblkio/

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
