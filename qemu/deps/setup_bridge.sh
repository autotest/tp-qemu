#!/bin/bash
set -x

_setup_bridge()
{
    #Get the Ethernet interface
    NDEV=$(ip route | grep default | grep -Po '(?<=dev )(\S+)' | awk 'BEGIN{ RS = "" ; FS = "\n" }{print $1}')
    #Get connection name
    CONID=$(nmcli device show $NDEV | awk -F: '/GENERAL.CONNECTION/ {print $2}' | awk '{$1=$1}1')

    nmcli con add type bridge ifname "$BRIDGE_IFNAME" con-name "$BRIDGE_IFNAME" stp no
    nmcli con modify "$CONID" master "$BRIDGE_IFNAME"
    nmcli con up "$CONID"
    [ $? -ne 0 ] && echo "NetworkManager Command failed" && exit 1
}

_chk_bridge_dev_ip()
{
    ## Check whether bridge device gets ip address
    START=`date +%s`
    while [ $(( $(date +%s) - 120 )) -lt $START ]; do
        IP_ADDR=$(ip address show "$BRIDGE_IFNAME" | grep "inet\b" | awk '{print $2}' | cut -d/ -f1)
        [[ -n "$IP_ADDR" ]] && echo "ip address of bridge device '$BRIDGE_IFNAME': $IP_ADDR" && exit 0
        sleep 5
    done
    echo "Fail to get ip address of bridge device '$BRIDGE_IFNAME' in 2 mins"
    exit 1
}

BRIDGE_IFNAME='switch'

nmcli conn show |grep "$BRIDGE_IFNAME" ||  _setup_bridge
_chk_bridge_dev_ip
