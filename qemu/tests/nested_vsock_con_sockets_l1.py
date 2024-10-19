import os
import time

from avocado.utils import path, process
from virttest import data_dir, error_context

from provider import message_queuing


def compile_nc_vsock_guest(test, vm, session):
    """
    Copy and compile nc-vsock in the guest

    :param test: QEMU test object
    :param vm: Object qemu_vm.VM
    :param session: vm session
    :return: Path to binary nc-vsock or None if compile failed
    """
    nc_vsock_dir = "/home/"
    nc_vsock_bin = "nc-vsock"
    nc_vsock_c = "nc-vsock.c"
    src_file = os.path.join(data_dir.get_deps_dir("nc_vsock"), nc_vsock_c)
    bin_path = os.path.join(nc_vsock_dir, nc_vsock_bin)
    rm_cmd = "rm -rf %s*" % bin_path
    session.cmd(rm_cmd)
    vm.copy_files_to(src_file, nc_vsock_dir)
    compile_cmd = "cd %s && gcc -o %s %s" % (nc_vsock_dir, nc_vsock_bin, nc_vsock_c)
    guest_status = session.cmd_status(compile_cmd)
    if guest_status != 0:
        session.cmd_output_safe(rm_cmd)
        session.close()
        test.error("Compile nc-vsock failed")
    return bin_path


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU nested vsock concatenate sockets test of L1

    1) Boot L2 guest vm with vsock device
    2) Concatenate sockets
    3) Receive file in L2 guest

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_file_l2(obj, msg):
        socat_cmd = params["socat_cmd"] % (vsock_port, vsock_port)
        process.system(socat_cmd, ignore_bg_processes=True, shell=True)

        session.sendline(cmd_receive)
        time.sleep(10)
        chksum_cmd = "md5sum %s" % tmp_file
        md5_received = session.cmd_output(chksum_cmd, timeout=60).split()[0]
        md5_origin = msg.split(":")[1]
        test.log.info("md5_origin: %s", md5_origin)
        test.log.info("md5_received: %s", md5_received)

        obj.set_msg_loop(False)
        obj.send_message("exit")

        if md5_origin != md5_received:
            test.fail("File got on L2 is not identical with the file on the host.")

        test.log.info("Test ended.")

    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    vsock_test_tool = params.get("vsock_test_tool")
    tmp_file = "/tmp/file_from_host"
    host_cid = params.get("host_cid", 2)
    vsock_port = params.get("vsock_port", 2345)

    disable_firewall = params.get("disable_firewall")
    session.cmd(disable_firewall, ignore_all_errors=True)

    host = params.get("mq_publisher")
    mq_port = params.get_numeric("mq_port", 2000)
    test.log.info("host:%s port:%s", host, mq_port)
    client = message_queuing.MQClient(host, mq_port)
    time.sleep(5)

    cmd_receive = None
    if vsock_test_tool == "ncat":
        tool_bin = path.find_command("ncat")
        cmd_receive = "%s --vsock %s %s > %s &" % (
            tool_bin,
            host_cid,
            vsock_port,
            tmp_file,
        )

    if vsock_test_tool == "nc_vsock":
        tool_bin = compile_nc_vsock_guest(test, vm, session)
        cmd_receive = "%s %s %s > %s &" % (tool_bin, host_cid, vsock_port, tmp_file)

    if cmd_receive is None:
        raise ValueError(f"unexpected test tool: {vsock_test_tool}")

    try:
        client.send_message("L1_up")
        client.register_msg("md5_origin:", _get_file_l2)
        client.msg_loop(timeout=180)
        test.log.debug("Finish msg_loop")
    finally:
        client.close()
        test.log.debug("MQ closed")
        session.cmd_output_safe("rm -rf %s" % tmp_file)
        if vsock_test_tool == "nc_vsock":
            session.cmd_output_safe("rm -rf %s*" % tool_bin)
