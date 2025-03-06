import logging
import os
import random
import time

import aexpect
from avocado.utils import path, process
from virttest import data_dir, error_context, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


def compile_nc_vsock(test, vm, session):
    """
    Copy and compile nc-vsock on both host and guest

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
    process.system(rm_cmd, shell=True, ignore_status=True)
    cmd_cp = "cp %s %s" % (src_file, nc_vsock_dir)
    process.system(cmd_cp)
    vm.copy_files_to(src_file, nc_vsock_dir)
    compile_cmd = "cd %s && gcc -o %s %s" % (nc_vsock_dir, nc_vsock_bin, nc_vsock_c)
    host_status = process.system(compile_cmd, shell=True)
    guest_status = session.cmd_status(compile_cmd)
    if (host_status or guest_status) != 0:
        process.system(rm_cmd, shell=True, ignore_status=True)
        session.cmd_output_safe(rm_cmd)
        session.close()
        test.error("Compile nc-vsock failed")
    return bin_path


def vsock_listen(tool_bin, port, session):
    """
    Open vsock listening process from guest

    :param tool_bin: path of binary vsock test tool
    :param port: the port to listen
    :param session: guest shell session
    :return: the shell session with opened vsock listening process
    """

    lstn_cmd = None
    if "ncat" in tool_bin:
        lstn_cmd = "%s --vsock -l %s" % (tool_bin, port)

    if "nc-vsock" in tool_bin:
        lstn_cmd = "%s -l %s" % (tool_bin, port)

    if lstn_cmd is None:
        raise ValueError(f"unexpected test tool: {tool_bin}")

    session.read_nonblocking(0, timeout=10)
    LOG_JOB.info("Listening to the vsock port from guest: %s", lstn_cmd)
    session.sendline(lstn_cmd)
    time.sleep(5)


def check_received_data(test, session, pattern):
    """
    Check if session received expected data

    :param test: QEMU test object
    :param session: Session object to be checked
    :param pattern: Expected pattern of session output
    :return: Error msg if not receive expected content, None if received
    """
    try:
        session.read_until_last_line_matches([pattern])
    except aexpect.ExpectError as e:
        if isinstance(e, aexpect.ExpectTimeoutError):
            test.fail(
                "Does not receive expected content: %s, output"
                " of session: %s" % (pattern, e.output)
            )
        else:
            test.fail(str(e))


def vsock_connect(tool_bin, guest_cid, port):
    """
    Connect to vsock port from host

    :param tool_bin: path of binary vsock test tool
    :param guest_cid: guest cid to connect
    :param port: port to connect
    :return: The vsock session from host side, being waiting for input
    """

    conn_cmd = None
    if "ncat" in tool_bin:
        conn_cmd = "%s --vsock %s %s" % (tool_bin, guest_cid, port)
    if "nc-vsock" in tool_bin:
        conn_cmd = "%s %s %s" % (tool_bin, guest_cid, port)
    if conn_cmd is None:
        raise ValueError(f"unexpected test tool: {tool_bin}")
    LOG_JOB.info("Connect to the vsock port on host: %s", conn_cmd)

    return aexpect.Expect(
        conn_cmd,
        auto_close=False,
        output_func=utils_misc.log_line,
        output_params=("vsock_%s_%s" % (guest_cid, port),),
    )


def send_data_from_guest_to_host(
    guest_session, tool_bin, guest_cid, tmp_file, file_size=1000
):
    """
    Generate a temp file and transfer it from guest to host via vsock

    :param guest_session: Guest session object
    :param tool_bin: Path to vsock test tool binary
    :param guest_cid: Guest cid to connected
    :param file_size: Desired file size to be transferred
    :return: The host vsock connection process
    """

    cmd_generate = "dd if=/dev/urandom of=%s count=%s bs=1M" % (tmp_file, file_size)
    guest_session.cmd_status(cmd_generate, timeout=600)
    port = random.randrange(1, 6000)
    cmd_transfer = None
    if "ncat" in tool_bin:
        cmd_transfer = "%s --vsock --send-only -l %s < %s" % (tool_bin, port, tmp_file)
    if "nc-vsock" in tool_bin:
        cmd_transfer = "%s -l %s < %s" % (tool_bin, port, tmp_file)
    if cmd_transfer is None:
        raise ValueError(f"unexpected test tool: {tool_bin}")
    error_context.context(
        "Transfer file from guest via command: %s" % cmd_transfer, LOG_JOB.info
    )
    guest_session.sendline(cmd_transfer)
    cmd_receive = None
    if "ncat" in tool_bin:
        cmd_receive = "%s --vsock %s %s > %s" % (tool_bin, guest_cid, port, tmp_file)
    if "nc-vsock" in tool_bin:
        cmd_receive = "%s %s %s > %s" % (tool_bin, guest_cid, port, tmp_file)
    if cmd_receive is None:
        raise ValueError(f"unexpected test tool: {tool_bin}")
    time.sleep(60)
    return aexpect.Expect(
        cmd_receive,
        auto_close=True,
        output_func=utils_misc.log_line,
        output_params=("%s.log" % tmp_file,),
    )


def check_guest_vsock_conn_exit(test, session, close_session=False):
    """
    Check if previous process exits and guest session returns to shell prompt

    :param test: QEMU test object
    :param session: Guest session object
    :param close_session: close the session finally if True
    """
    try:
        session.read_up_to_prompt(timeout=120)
    except aexpect.ExpectTimeoutError:
        test.fail(
            "vsock listening prcoess inside guest"
            " does not exit after close host nc-vsock connection."
        )
    finally:
        if close_session:
            session.close()


@error_context.context_aware
def run(test, params, env):
    """
    Vsock basic function test

    1. Boot guest with vhost-vsock-pci device
    2. Download and compile nc-vsock on both guest and host if needed
    3. Start listening inside guest
    4. Connect guest CID from host
    5. Input character, e.g. 'Hello world'
    6. Check if guest receive the content correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def clean(tmp_file):
        """Clean the environment"""
        cmd_rm = "rm -rf %s" % tmp_file
        if vsock_test_tool == "nc_vsock":
            cmd_rm += "; rm -rf %s*" % tool_bin
        session.cmd_output_safe(cmd_rm)
        process.system(cmd_rm, shell=True, ignore_status=True)
        if host_vsock_session.is_alive():
            host_vsock_session.close()
        session.close()

    vm = env.get_vm(params["main_vm"])
    tmp_file = "/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)
    vm.verify_alive()
    session = vm.wait_for_login()
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    port = random.randrange(1, 6000)
    vsock_test_tool = params["vsock_test_tool"]

    host_vsock_session = None
    if vsock_test_tool == "ncat":
        tool_bin = path.find_command("ncat")
        vsock_listen(tool_bin, port, session)
        host_vsock_session = vsock_connect(tool_bin, guest_cid, port)

    if vsock_test_tool == "nc_vsock":
        tool_bin = compile_nc_vsock(test, vm, session)
        vsock_listen(tool_bin, port, session)
        host_vsock_session = vsock_connect(tool_bin, guest_cid, port)
        connected_str = r"Connection from cid*"
        check_received_data(test, session, connected_str)

    if host_vsock_session is None:
        raise ValueError(f"unexpected test tool: {tool_bin}")

    send_data = "Hello world"
    error_context.context('Input "Hello world" to vsock.', test.log.info)
    host_vsock_session.sendline(send_data)
    check_received_data(test, session, send_data)
    host_vsock_session.close()
    check_guest_vsock_conn_exit(test, session, close_session=True)

    # Transfer data from guest to host
    session = vm.wait_for_login()
    rec_session = send_data_from_guest_to_host(session, tool_bin, guest_cid, tmp_file)
    utils_misc.wait_for(lambda: not rec_session.is_alive(), timeout=20)
    check_guest_vsock_conn_exit(test, session)
    cmd_chksum = "md5sum %s" % tmp_file
    md5_origin = session.cmd_output(cmd_chksum).split()[0]
    md5_received = process.system_output(cmd_chksum).split()[0].decode()
    if md5_received != md5_origin:
        clean(tmp_file)
        test.fail(
            "Data transfer not integrated, the original md5 value"
            " is %s, while the md5 value received on host is %s"
            % (md5_origin, md5_received)
        )
    clean(tmp_file)
