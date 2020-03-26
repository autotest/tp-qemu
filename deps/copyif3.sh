copyif2() {
if test $# -lt 2 || test $# -gt 3; then
  echo 'usage: copyif src dst [bitmap]'
  return 1
fi
if test -z "$3"; then
  map_from="-f raw $1"
  state=true
else
  port=$(echo "$1" | cut -d':' -f3 | cut -d'/' -f1)
  name=$(echo "$1" | cut -d':' -f3 | cut -d'/' -f2)
  host=$(echo "$1" | cut -d':' -f2 | cut -d'/' -f3)
  map_from="--image-opts driver=nbd,export=${name},server.type=inet"
  map_from+=",server.host=${host},server.port=${port}"
  map_from+=",x-dirty-bitmap=qemu:dirty-bitmap:$3"
  state=false
fi
map_out="./map.out"
qemu-img info -f raw $1 || return
qemu-img info -f qcow2 $2 || return
qemu-img map --output=json $map_from > $map_out
ret=0
qemu-img rebase -u -f qcow2 -F raw -b $1 $2

while read line; do
  [[ $line =~ .*start.:.([0-9]*).*length.:.([0-9]*).*data.:.$state.* ]] || continue
  start=${BASH_REMATCH[1]} len=${BASH_REMATCH[2]}
  echo
  echo " $start $len:"
  qemu-io -C -c "r $start $len" -f qcow2 $2
done < ${map_out}
rm -f ${map_out}
qemu-img rebase -u -f qcow2 -b '' $2
if test $ret = 0; then echo 'Success!'; fi
return $ret
}

copyif2 $1 $2 $3
