import logging
import re

from virttest import error_context


def fill_partitions(test, params, session, partition, deeply=False):
    """
    Fill up the specified partitions.
    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param session: ShellSession object.
    :param partition: Specified partition,
    :param deeply: fill up partition with block size of 512b.
    """
    fillup_cmd = params["fillup_cmd"]
    clean_cmd = params["clean_cmd"]
    fillup_timeout = int(params["fillup_timeout"])
    fillup_size = int(params["fillup_size"])
    prefix = re.search(r'%s/.*\*$', clean_cmd).group().lstrip('%s/').rstrip('*')
    number = 0

    info = "Start shallow filling the %s partition." % partition
    if deeply:
        info = "Start deep filling the %s partition with 512b." % partition
    error_context.context(info, logging.info)

    while 1:
        # As we want to test the backing file, so bypass the cache
        cmd = fillup_cmd % (partition, number, fillup_size)
        if deeply:
            cmd = 'dd if=/dev/zero of=%s/%s512b bs=512b oflag=direct' \
                  % (partition, prefix)
        logging.debug(cmd)
        s, o = session.cmd_status_output(cmd, timeout=fillup_timeout)
        if "No space left on device" in o:
            if not deeply:
                fill_partitions(test, params, session, partition, True)
            break
        elif s != 0:
            test.fail("Command dd failed to execute: %s" % o)
        number += 1


@error_context.context_aware
def run(test, params, env):
    """
    Fill up disk test:
    Purpose to expand the qcow2 file to its max size by filling partitions.
    Suggest to test rebooting vm after this test.
    1). Fill up guest disk (root mount point) using dd if=/dev/zero.
    2). Clean up big files in guest with rm command.


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session2 = vm.wait_for_serial_login(timeout=login_timeout)
    filled_partition = params.get("guest_testdir")

    logging.debug('Check info of parttions: ')
    parts_info = session.cmd_output('lsblk')
    logging.debug(parts_info)
    all_partitions = [str(mp.split()[-1]) for mp in parts_info.splitlines()
                      if re.search(r'\d+\s+(lvm|part)\s+/', mp)]

    try:
        if not filled_partition:
            # fill up all the partitions exclude [SWAP].
            for partition in all_partitions:
                fill_partitions(test, params, session, partition)
        else:
            # fill up the specify partition for other cases,such as lvm.lvm_fill.
            fill_partitions(test, params, session, filled_partition)
        logging.debug("Successfully filled up the disk")
    finally:
        logging.debug('Check capacity of disk:')
        cap_info = session.cmd_output('df -h')
        logging.debug(cap_info)

        error_context.context("Cleaning the temporary files...", logging.info)
        try:
            if not filled_partition:
                for partition in all_partitions:
                    clean_cmd = params["clean_cmd"] % partition
                    session2.cmd(clean_cmd, ignore_all_errors=True)
            else:
                clean_cmd = params["clean_cmd"] % filled_partition
                session2.cmd(clean_cmd, ignore_all_errors=True)
        finally:
            if not filled_partition:
                for partition in all_partitions:
                    show_fillup_dir_cmd = params["show_fillup_dir_cmd"] \
                                          % partition
                    output = session2.cmd(show_fillup_dir_cmd,
                                          ignore_all_errors=True)
                    logging.debug("The fill up %s partition shows:\n %s"
                                  % (partition, output))
            else:
                show_fillup_dir_cmd = params["show_fillup_dir_cmd"] \
                                      % filled_partition
                output = session2.cmd(show_fillup_dir_cmd,
                                      ignore_all_errors=True)
                logging.debug("The fill up %s partition shows:\n %s"
                              % (filled_partition, output))
            if session:
                session.close()
            if session2:
                session2.close()
