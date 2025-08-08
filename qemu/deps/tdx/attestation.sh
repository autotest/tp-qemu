set -e
report=/sys/kernel/config/tsm/report/report0
mkdir $report
dd if=/dev/urandom bs=64 count=1 > $report/inblob
hexdump -C $report/outblob
pip install ecdsa pyopenssl pyasn1_modules
# workaround, temporary test script
wget $1
if [ -f "tdx.py" ]; then
    python tdx.py $report/outblob
else
    echo "tdx.py is not executable."
    exit 1
fi
