import logging
import re

from aexpect import ShellCmdError
from virttest import remote
from virttest import utils_misc
from virttest import utils_net
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test Step:
        1. boot up three virtual machine
        2. transfer file from guest1 to guest2, check md5
        3. in guest 3 try to capture the packets(guest1 <-> guest2)
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """
    def data_mon(session, cmd, timeout):
        try:
            session.cmd(cmd, timeout)
        except ShellCmdError, e:
            if re.findall(catch_date % (addresses[1], addresses[0]), str(e)):
                test.fail("God! Capture the transfet data:'%s'" % str(e))
            logging.info("Guest3 catch data is '%s'" % str(e))

    timeout = int(params.get("login_timeout", '360'))
    password = params.get("password")
    username = params.get("username")
    shell_port = params.get("shell_port")
    tmp_dir = params.get("tmp_dir", "/tmp/")
    clean_cmd = params.get("clean_cmd", "rm -f")
    filesize = int(params.get("filesize", '100'))

    tcpdump_cmd = params.get("tcpdump_cmd")
    dd_cmd = params.get("dd_cmd")
    catch_date = params.get("catch_data", "%s.* > %s.ssh")
    md5_check = params.get("md5_check", "md5sum %s")
    mon_process_timeout = int(params.get("mon_process_timeout", "1200"))
    sessions = []
    addresses = []
    vms = []

    error_context.context("Init boot the vms")
    for vm_name in params.get("vms", "vm1 vm2 vm3").split():
        vms.append(env.get_vm(vm_name))
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())
    mon_session = vms[2].wait_for_login(timeout=timeout)
    mon_macaddr = vms[2].get_mac_address()

    src_file = (tmp_dir + "src-%s" % utils_misc.generate_random_string(8))
    dst_file = (tmp_dir + "dst-%s" % utils_misc.generate_random_string(8))

    try:
        # Before transfer, run tcpdump to try to catche data
        error_msg = "In guest3, try to capture the packets(guest1 <-> guest2)"
        error_context.context(error_msg, logging.info)
        if params.get("os_type") == "linux":
            if_func = utils_net.get_linux_ifname
            args = (mon_session, mon_macaddr)
        else:
            if_func = utils_net.get_windows_nic_attribute
            args = (mon_session, "macaddress", mon_macaddr, "netconnectionid")
        interface_name = if_func(*args)
        tcpdump_cmd = tcpdump_cmd % (addresses[1], addresses[0],
                                     interface_name)
        dthread = utils_misc.InterruptedThread(data_mon,
                                               (sessions[2],
                                                tcpdump_cmd,
                                                mon_process_timeout))

        logging.info("Tcpdump mon start ...")
        logging.info("Creating %dMB file on guest1", filesize)
        sessions[0].cmd(dd_cmd % (src_file, filesize), timeout=timeout)
        dthread.start()

        error_context.context("Transferring file guest1 -> guest2",
                              logging.info)
        if params.get("os_type") == "windows":
            cp_cmd = params["copy_cmd"]
            cp_cmd = cp_cmd % (addresses[1], params['file_transfer_port'],
                               src_file, dst_file)
            sessions[0].cmd_output(cp_cmd)
        else:
            remote.scp_between_remotes(addresses[0], addresses[1],
                                       shell_port, password, password,
                                       username, username, src_file, dst_file)

        error_context.context("Check the src and dst file is same",
                              logging.info)
        src_md5 = sessions[0].cmd_output(md5_check % src_file).split()[0]
        dst_md5 = sessions[1].cmd_output(md5_check % dst_file).split()[0]

        if dst_md5 != src_md5:
            debug_msg = "Files md5sum mismatch!"
            debug_msg += "source file md5 is '%s', after transfer md5 is '%s'"
            test.fail(debug_msg % (src_md5, dst_md5), logging.info)
        logging.info("Files md5sum match, file md5 is '%s'" % src_md5)

        error_context.context("Checking network private", logging.info)
        tcpdump_check_cmd = params["tcpdump_check_cmd"]
        tcpdump_kill_cmd = params["tcpdump_kill_cmd"]
        tcpdump_check_cmd = re.sub("ADDR0", addresses[0], tcpdump_check_cmd)
        tcpdump_check_cmd = re.sub("ADDR1", addresses[1], tcpdump_check_cmd)
        status = mon_session.cmd_status(tcpdump_check_cmd)
        if status:
            test.error("Tcpdump process terminate exceptly")
        mon_session.cmd(tcpdump_kill_cmd)
        dthread.join()

    finally:
        sessions[0].cmd(" %s %s " % (clean_cmd, src_file))
        sessions[1].cmd(" %s %s " % (clean_cmd, src_file))
        if mon_session:
            mon_session.close()
        for session in sessions:
            if session:
                session.close()
