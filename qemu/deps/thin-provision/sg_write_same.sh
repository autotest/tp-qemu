#!/bin/bash

if ! which sg_write_same; then
  echo "Please install sg3_utils first"
  exit 1
fi
if [[ "x$1" == "x" ]];then
  echo "Miss device"
  exit 1
fi
dev=$1
yes | head -n 2048 >buf
sg_write_same --in buf --num=32 --lba=80 ${dev}
sg_write_same --in /dev/zero --num=96 --lba=0 ${dev}
sg_write_same -U --in /dev/zero --num=16 --lba=0 ${dev}
/usr/bin/time --format="%e" -o /tmp/t1 sg_write_same --in buf --num=65536 --lba=131074 ${dev}
/usr/bin/time --format="%e" -o /tmp/t2 sg_write_same --in /dev/zero --num=65534 --lba=196608 ${dev}
echo "Expect Write same(10): Illegal request"
sg_write_same --in /dev/zero --num=0 --lba=128 ${dev}

t1=`tail -n 1 /tmp/t1`
t2=`tail -n 1 /tmp/t2`

if expr $t2 \> $t1;then
  echo "Find unexpect result $t1 $t2"
  exit 1
fi

echo "Time of sg_write_same $t1:$t2"
