trap 'kill $(jobs -p)' EXIT SIGINT

for i in `seq 0 32` ; do
  while true ; do
    sg_luns /dev/sdb > /dev/null 2>&1
  done &
done
echo "wait"
wait
