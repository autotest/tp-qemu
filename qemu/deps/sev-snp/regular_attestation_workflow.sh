#!/bin/bash
set -e

fetch_retry() {
    local command=$1
    local max_retries=3
    local retry_count=0

    while (( retry_count < max_retries )); do
        eval "$command"
        if [[ $? -eq 0 ]]; then
            return 0
        fi
        retry_count=$((retry_count + 1))
        echo "Command '$command' failed. Retry $retry_count/$max_retries in 20s..."
        sleep 20
    done
    echo "Command '$command' failed after $max_retries attempts."
    return 1
}

# Verify regular attestation workflow on snp guest
snpguest report attestation-report.bin request-data.txt --random
snpguest display report attestation-report.bin

# Get cpu model
cpu_familly_id=$(cat /proc/cpuinfo | grep 'cpu family' | head -1 | cut -d ":" -f 2 | tr -d " ")
model_id=$(cat /proc/cpuinfo | grep 'model' | head -1 | cut -d ":" -f 2 | tr -d " ")
dict_cpu=([251]="milan" [2517]="genoa" [2617]="turin")
cpu_model=${dict_cpu[${cpu_familly_id}${model_id}]}

# Fetch cert
set +e
fetch_retry "snpguest fetch ca pem ${cpu_model} ./ -e vcek"
if [[ $? -ne 0 ]]; then
   echo "ok"
   exit 1
fi

fetch_retry "snpguest fetch vcek pem ${cpu_model} ./ attestation-report.bin"
if [[ $? -ne 0 ]]; then
    exit 1
fi

# Verify certs
set -e
snpguest verify certs ./
snpguest verify attestation ./ attestation-report.bin
