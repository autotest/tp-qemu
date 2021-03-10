# For ppc64 (big endian)
# assemble with as -mregnames -o million.o million.s ; ld -o million million.o

# count for 1 million instructions
#   total is 1 + 1 + 1 + 999994 + 3
	.globl _start
_start: /* OPB */
	.llong	._start
	.llong	0

._start:
	lis	r3,999994@ha
	addi	r3,r3,999994@l
	mtctr	r3
test_loop:
	bdnz	test_loop

exit:
	li	r3,0			# return status 0
	li	r0,1			# exit(2) syscall number
	sc
	b	.
