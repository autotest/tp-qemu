obj-m := force_panic.o
KDIR := /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)
default:
	make -C $(KDIR) M=$(PWD) modules
