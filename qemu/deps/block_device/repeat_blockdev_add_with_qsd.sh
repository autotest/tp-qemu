#!/bin/sh

QEMU_IMG=qemu-img
QSD=qemu-storage-daemon

if ! which ${QSD};then echo "${QSD} does not exist";exit 1; fi

TMP_DIR=`mktemp -d`
echo "${TMP_DIR}"
TOP_FILE="${TMP_DIR}/top.qcow2"

"$QEMU_IMG" create -f qcow2 -F raw -b null-co:// ${TOP_FILE}

(echo '{"execute": "qmp_capabilities"}'
 sleep 1
 while true; do
     echo '{"execute": "blockdev-add", "arguments": {"driver": "qcow2", "node-name": "tmp", "backing": "node0", "file": {"driver": "file", "filename": "'${TOP_FILE}'"}}}'
     echo '{"execute": "blockdev-del", "arguments": {"node-name": "tmp"}}'
 done) | \
"$QSD" \
    --chardev stdio,id=stdio \
    --monitor mon0,chardev=stdio \
    --object iothread,id=iothread0 \
    --blockdev null-co,node-name=node0,read-zeroes=true \
    --nbd-server addr.type=unix,addr.path=${TMP_DIR}/nbd.sock \
    --export nbd,id=exp0,node-name=node0,iothread=iothread0,fixed-iothread=true,writable=true \
    --pidfile ${TMP_DIR}/qsd.pid \
    &

while [ ! -f ${TMP_DIR}/qsd.pid ]; do
    true
done

"$QEMU_IMG" bench -f raw -c 4000000 nbd+unix:///node0\?socket=${TMP_DIR}/nbd.sock
ret=$?

kill %1

rm -rf ${TMP_DIR}
exit $ret
