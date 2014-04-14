PROG = clock_getres
SRC = clock_getres.c
LIBS = -lrt

all: $(PROG)

$(PROG):
	$(CC) $(SRC) $(CFLAGS) $(LIBS) -o $(PROG)
clean:
	rm -f $(PROG)
