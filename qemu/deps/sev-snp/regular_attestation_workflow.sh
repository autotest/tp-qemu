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
        echo "[$retry_count/$max_retries] try: $command"
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

output="$(snpguest -V)"
version="${output#snpguest }"
echo "snpguest version: $version"

# Verify regular attestation workflow on snp guest
(set -x; snpguest report attestation-report.bin request-data.txt --random)
if [[ ! -f attestation-report.bin ]]; then
    echo "attestation-report.bin not created."
    exit 1
fi
(set -x; snpguest display report attestation-report.bin)
check_status "Failed display attestation-report."

case "${version#snpguest }" in
    0.8.*)
        fetch_retry "snpguest fetch ca -e vcek pem ${cpu_model} ./"
        check_status "Failed to fetch CA certificate."
        fetch_retry "snpguest fetch vcek pem ${cpu_model} ./ attestation-report.bin"
        check_status "Failed to fetch VCEK certificate."
        ;;
    *)
        fetch_retry "snpguest fetch ca -e vcek pem ./ ${cpu_model}"
        check_status "Failed to fetch CA certificate."
        fetch_retry "snpguest fetch vcek -p ${cpu_model} pem ./ attestation-report.bin"
        check_status "Failed to fetch VCEK certificate."
        ;;
esac

# Verify certs
(set -x; snpguest verify certs ./)
check_status "Failed to verify certificates."

case "$version" in
    0.8.*)
        (set -x; snpguest verify attestation ./ attestation-report.bin)
        check_status "Failed to verify attestation."
        ;;
    *)
        (set -x; snpguest verify attestation -p ${cpu_model} ./ attestation-report.bin)
        check_status "Failed to verify attestation."
        ;;
esac
