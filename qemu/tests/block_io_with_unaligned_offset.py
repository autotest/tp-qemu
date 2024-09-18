"""qemu-io with unaligned offset"""

from avocado.utils import process


def run(test, params, env):
    """qemu-io with unaligned offset on simulated 4k disk.
    Test Steps:
    1) Create loop device with --sector-size 4096
    2) Execute qemu-io with aligned offset
    3) Execute qemu-io with unaligned offset
    """
    logger = test.log
    io_cmd = params["io_cmd"]
    cmd = "cat %s" % params["loop_dev"]
    loop_dev = process.system_output(cmd, shell=True).decode()
    logger.debug("Create loop device on:%s", loop_dev)

    cmd = io_cmd % (4096, loop_dev)
    logger.debug("Execute IO with aligned offset:%s", cmd)
    process.run(cmd, shell=True)

    cmd = io_cmd % (512, loop_dev)
    logger.debug("Execute IO with unaligned offset:%s", cmd)
    process.run(cmd, shell=True)
