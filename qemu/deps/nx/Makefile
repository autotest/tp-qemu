CFLAGS+=-Wall

.PHONY: clean

nx_exploit: x64_sc_rdo.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f nx_exploit
