#!/bin/bash
set -e
# Verify regular attestation workflow on snp guest
snpguest report attestation-report.bin request-data.txt --random
snpguest display report attestation-report.bin
# get cpu model
cpu_familly_id=$(cat /proc/cpuinfo | grep 'cpu family' | head -1 | cut -d ":" -f 2 | tr -d " ")
model_id=$(cat /proc/cpuinfo | grep 'model' | head -1 | cut -d ":" -f 2 | tr -d " ")
dict_cpu=([251]="milan" [2517]="genoa")
cpu_model=${dict_cpu[${cpu_familly_id}${model_id}]}
snpguest fetch ca pem ${cpu_model} ./ -e vcek
snpguest fetch vcek pem ${cpu_model} ./ attestation-report.bin
snpguest verify certs ./
snpguest verify attestation ./ attestation-report.bin
