import mmap
import sys

l = 1024
f = open(sys.argv[1], "a+b")
f.truncate(l)
m = mmap.mmap(f.fileno(), 1024, access=mmap.ACCESS_WRITE)
m[0:4] = b"0000"
m.flush()
print(m.size())
m[0:4] = b"0000"
m.flush()
print(m.size())
