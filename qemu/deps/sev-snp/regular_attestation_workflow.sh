#!/bin/bash

check_status() {
    if [ $? -ne 0 ]; then
        echo "Error: $1"
        exit 1
    fi
}

# Check for the required CPU model parameter
if [[ -z "$1" ]]; then
    echo "Error: cpu_model parameter is required."
    echo "Usage: $0 <cpu_model>"
    exit 1
fi

cpu_model="$1"

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
if [[ ! -f attestation-report.bin ]]; then
    echo "attestation-report.bin not created."
    exit 1
fi
snpguest display report attestation-report.bin
check_status "Failed display attestation-report."

# Fetch cert
fetch_retry "snpguest fetch ca -e vcek pem ./ ${cpu_model}"
check_status "Failed to fetch CA certificate."

fetch_retry "snpguest fetch vcek -p ${cpu_model} pem ./ attestation-report.bin"
check_status "Failed to fetch VCEK certificate."

# Verify certs
snpguest verify certs ./
check_status "Failed to verify certificates."
snpguest verify attestation -p ${cpu_model} ./ attestation-report.bin
check_status "Failed to verify attestation."
