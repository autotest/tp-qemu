# Multi disks IO
echo "$$"
usage="-s <size> -d <devices> -n <repeats>"
devs=""
size=10G
repeats=1

while getopts 's:d:n:h' OPT; do
    case $OPT in
    s) size="$OPTARG" ;;
    d) devs="$OPTARG" ;;
    n) repeats="$OPTARG" ;;
    h)
      echo -e "${usage}"
      exit 0
      ;;
    ?)
      echo -e "${usage}"
      exit 0
      ;;
    esac
done

echo "$devs"
echo "$$" > /tmp/mpid
trap 'kill $(jobs -p)' EXIT SIGINT
for dev in $devs;do
  echo "IO on disk $dev"
  mkdir -p /home/$dev
  if mount|grep /home/$dev;then umount /home/$dev;fi
  mkfs.xfs -f /dev/$dev
  mount /dev/$dev /home/$dev
  for (( n=0; n < ${repeats}; n++ ));do
    fio --size=$size --direct=0 --ioengine=libaio --filename=/home/$dev/test.dat --name=${dev}test --bs=1M --rw=randrw >/dev/null;
    sleep 5
  done &

done

echo "Wait ..."
wait
echo "Over."
echo "" > /tmp/mpid
