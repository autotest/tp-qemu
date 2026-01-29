#!/bin/bash

set -e

# Define test directory
TEST_DIR="pccsadmin_test"
mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

# Start tests
PCKIDRetrievalTool
pccsadmin collect
if [ $? -ne 0 ]; then
    echo "pccsadmin collect failed"
    exit 1
fi
cat platform_list.json
# pccsadmin fetch
expect -c "
set timeout 60
spawn pccsadmin fetch
expect \"Please input ApiKey for Intel PCS:\"
send \"$PCCS_PRIMARY_API_KEY\r\"
expect \"Would you like to remember Intel PCS ApiKey in OS keyring? (y/n)\"
send \"n\r\"
expect eof

# Check if platform_collaterals.json was generated
if [ ! -f platform_collaterals.json ]; then
    echo "Pccsadmin fetch failed, platform_collaterals.json was not generated."
    exit 1
fi

# pccsadmin put
expect -c "
set timeout 60
spawn pccsadmin put
expect \"Please input your administrator password for PCCS service:\"
send \"$AdminTokenHash\r\"
expect \"Would you like to remember password in OS keyring? (y/n)\"
send \"n\r\"
expect eof
" | grep -q "Collaterals uploaded successfully"
if [ $? -ne 0 ]; then
    echo "Pccsadmin put failed, collaterals were not uploaded successfully."
    exit 1
fi

# pccsadmin get
expect -c "
set timeout 60
spawn pccsadmin get -s '[]'
expect \"Please input your administrator password for PCCS service:\"
send \"$AdminTokenHash\r\"
expect \"Would you like to remember password in OS keyring? (y/n)\"
send \"n\r\"
expect eof
" | grep -q "saved successfully."
if [ $? -ne 0 ]; then
    echo "Pccsadmin get failed, collaterals were not retrieved successfully."
    exit 1
fi

# pccsadmin refresh
expect -c "
set timeout 60
spawn pccsadmin refresh
expect \"Please input your administrator password for PCCS service:\"
send \"$AdminTokenHash\r\"
expect \"Would you like to remember password in OS keyring? (y/n)\"
send \"n\r\"
expect eof
" | grep -q "The cache database was refreshed successfully."
if [ $? -ne 0 ]; then
    echo "Pccsadmin refresh failed."
    exit 1
fi

# pccsadmin cache
expect -c "
set timeout 60
spawn pccsadmin cache -i platform_list.json -o ./my_cache
expect \"Please input ApiKey for Intel PCS:\"
send \"$PCCS_PRIMARY_API_KEY\r\"
expect \"Would you like to remember Intel PCS ApiKey in OS keyring? (y/n)\"
send \"n\r\"
expect eof
" | grep -q "saved successfully"

if [ $? -ne 0 ]; then
    echo "Pccsadmin cache failed."
    exit 1
fi

# END tests
cd ..
rm -rf "$TEST_DIR"