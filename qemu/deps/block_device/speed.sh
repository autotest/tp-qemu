#!/bin/bash
set_io_limit() {
  speed=${1}kb/s
  #read
  iptables -A OUTPUT -p tcp --sport 2049 -m hashlimit --hashlimit-name conn_limitA --hashlimit-upto $speed -j ACCEPT
  iptables -A OUTPUT -p tcp --sport 2049 -j DROP
  #write
  iptables -A OUTPUT -p tcp --dport 2049 -m hashlimit --hashlimit-name conn_limitB --hashlimit-upto $speed -j ACCEPT
  iptables -A OUTPUT -p tcp --dport 2049 -j DROP
  iptables -L OUTPUT --line-numbers | grep nfs
}

remove_io_limit() {
  rules=`iptables -L OUTPUT --line-numbers | grep :nfs|awk '{print $1}'|sort -nr`
  echo "Remove `echo $rules|tr -d '\n'`"
  for r in $rules
  do
    iptables -D OUTPUT $r
  done

  iptables -L OUTPUT --line-numbers

}

limit_speed(){
  echo "set limit $1 $2 `date +%M:%S`"
  set_io_limit $1
  sleep $2
  if [ $# > 2 ];then
    echo "unlimit sleep $3 `date +%M:%S`"
    remove_io_limit
    sleep $3
  fi
}

start_limit() {

  limit_speed 50 10 5
  limit_speed 100 300 1
  limit_speed 100 360 1
  limit_speed 100 300 1
  limit_speed 100 240 1
  limit_speed 100 300 1

}

remove_io_limt
start_limit
