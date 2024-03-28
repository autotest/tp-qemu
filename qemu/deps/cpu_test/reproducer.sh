#!/bin/bash

VMID=cd577610-d8d1-457a-a0ea-f6321debcc14
HIGH=7000
LOW=1000
WAIT=1

balloon() {
	amount=$1
	echo balloon to $amount ...
	virsh qemu-monitor-command $VMID --hmp "balloon $amount"
	echo wait until actual=$amount ...
	while true;
	do
		info=$(virsh qemu-monitor-command $VMID --hmp "info balloon" | head -1 | sed 's/.*=//; s/[^0-9]*$//')
		if [[ $info == $amount ]]; then
			echo "value reached!"
			break
		fi
		echo "value not reached (current=${info}, target=${amount}), waiting..."
		sleep 2
	done
}

while true;
do
	balloon $HIGH
	sleep 1
	balloon $LOW
done
