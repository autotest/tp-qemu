#!/bin/sh
iface=$1
file1=/tmp/pass1
file2=/tmp/pass2
vns_pre=10
vns=1024
proto=802.1ad
if [ -z $iface ]
then
    echo "please provide a interface, e.g. `basename $0` eth0"
    exit 0
else
    echo "you are testing with $iface."
fi
if [ -e $file1 ] && [ -e $file2 ]
then
    rm -f $file1 $file2
fi

for i in `seq $vns_pre`
do
    ip link add link $iface name v1v$i type vlan proto $proto id $i
    if [ $? -eq 0 ]
    then
	echo $i>>$file1
    else
	echo "v1v$i is not created"
    fi
    sleep 2
    for s in `seq $vns`
    do
        ip link add link v1v$i name v2v$i\_$s type vlan id $s
        if [ $? -eq 0 ]
	then
	    echo $i\_$s>>$file2
	else
	    echo "v2v$i\_$s is not created"
	fi
    done
done
ret1=`cat $file1 |wc -l`
ret2=`cat $file2 |wc -l`
if [ $ret1 -eq $vns_pre ] && [ $ret2 -eq $((vns_pre*vns)) ]
then
    echo "$ret2 dot1ad vlans created successfully"
else
    echo "$ret2 dot1ad vlans created, case failed, please check"
    exit 1
fi
