set -e
report=/sys/kernel/config/tsm/report/report0
mkdir $report
dd if=/dev/urandom bs=64 count=1 > $report/inblob
hexdump -C $report/outblob
wget https://file.rdu.redhat.com/~berrange/tdx.py
pip install ecdsa pyopenssl pyasn1_modules
python tdx.py $report/outblob
