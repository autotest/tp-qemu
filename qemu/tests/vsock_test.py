import os
import random
import logging
import aexpect

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_misc


def compile_nc_vsock(test, vm, session):
    """
    Copy and compile nc-vsock on both host and guest

    :param test: QEMU test object
    :param vm: Object qemu_vm.VM
    :param session: vm session
    :return: Path to binary nc-vsock or None if compile failed
    """
    nc_vsock_dir = '/home/'
    nc_vsock_bin = 'nc-vsock'
    nc_vsock_c = 'nc-vsock.c'
    src_file = os.path.join(data_dir.get_deps_dir("nc_vsock"), nc_vsock_c)
    bin_path = os.path.join(nc_vsock_dir, nc_vsock_bin)
    rm_cmd = 'rm -rf %s*' % bin_path
    session.cmd(rm_cmd)
    process.system(rm_cmd, shell=True, ignore_status=True)
    cmd_cp = "cp %s %s" % (src_file, nc_vsock_dir)
    process.system(cmd_cp)
    vm.copy_files_to(src_file, nc_vsock_dir)
    compile_cmd = "cd %s && gcc -o %s %s" % (
        nc_vsock_dir, nc_vsock_bin, nc_vsock_c)
    host_status = process.system(compile_cmd, shell=True)
    guest_status = session.cmd_status(compile_cmd)
    if (host_status or guest_status) != 0:
        process.system(rm_cmd, shell=True, ignore_status=True)
        session.cmd_output_safe(rm_cmd)
        session.close()
        test.error("Compile nc-vsock failed")
    return bin_path


def nc_vsock_listen(nc_vsock_bin, port, session):
    """
    Open nc-vsock listening process from guest, cmd: nc-vsock -l $port

    :param nc_vsock_bin: path of binary nc-vsock
    :param port: the port to listen
    :param session: guest shell session
    :return: the shell session with opened vsock listening process
    """
    nc_vsock_cmd = "%s -l %s" % (nc_vsock_bin, port)
    session.read_nonblocking(0, timeout=10)
    logging.info("Listening to the vsock port from guest: %s" % nc_vsock_cmd)
    session.sendline(nc_vsock_cmd)


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
            test.fail("Does not receive expected content: %s, output"
                      " of session: %s" % (pattern, e.output))
        else:
            test.fail(str(e))


def nc_vsock_connect(nc_vsock_bin, guest_cid, port):
    """
    Connect to vsock port from host, cmd: nc-vsock $guest_cid $port

    :param nc_vsock_bin: path of binary nc-vsock
    :param guest_cid: guest cid to connect
    :param port: port to connect
    :return: The vsock session from host side, being waiting for input
    """
    nc_vsock_cmd = "%s %s %s" % (nc_vsock_bin, guest_cid, port)
    logging.info("Connect to the vsock port on host: %s" % nc_vsock_cmd)
    return aexpect.Expect(
        nc_vsock_cmd,
        auto_close=False,
        output_func=utils_misc.log_line,
        output_params=("vsock_%s_%s" % (guest_cid, port),))


def send_data_from_guest_to_host(guest_session, nc_vsock_bin,
                                 guest_cid, tmp_file, file_size=1000):
    """
    Generate a temp file and transfer it from guest to host via vsock

    :param guest_session: Guest session object
    :param nc_vsock_bin: Path to nc-vsock binary
    :param guest_cid: Guest cid to connected
    :param file_size: Desired file size to be transferred
    :return: The host nc-vsock connection process
    """

    cmd_generate = 'dd if=/dev/urandom of=%s count=%s bs=1M' % (tmp_file, file_size)
    guest_session.cmd_status(cmd_generate, timeout=600)
    port = random.randrange(1, 6000)
    cmd_transfer = '%s -l %s < %s' % (nc_vsock_bin, port, tmp_file)
    error_context.context('Transfer file from guest via command: %s'
                          % cmd_transfer, logging.info)
    guest_session.sendline(cmd_transfer)
    cmd_receive = '%s %s %s > %s' % (nc_vsock_bin, guest_cid, port, tmp_file)
    return aexpect.Expect(cmd_receive,
                          auto_close=True,
                          output_func=utils_misc.log_line,
                          output_params=('%s.log' % tmp_file,))


def check_guest_nc_vsock_exit(test, session, close_session=False):
    """
    Check if previous process exits and guest session returns to shell prompt

    :param test: QEMU test object
    :param session: Guest session object
    :param close_session: close the session finally if True
    """
    try:
        session.read_up_to_prompt(timeout=10)
    except aexpect.ExpectTimeoutError:
        test.fail("nc-vsock listening prcoess inside guest"
                  " does not exit after close host nc-vsock connection.")
    finally:
        if close_session:
            session.close()


@error_context.context_aware
def run(test, params, env):
    """
    Vsock basic function test

    1. Boot guest with vhost-vsock-pci device
    2. Download and compile nc-vsock on both guest and host
    3. Start listening inside guest, nc-vsock -l $port
    4. Connect guest CID from host, nc-vsock $guest_cid $port
    5. Input character, e.g. 'Hello world'
    6. Check if guest receive the content correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def clean(tmp_file=None):
        """ Clean the environment """
        cmd_rm = "rm -rf %s*" % nc_vsock_bin
        if tmp_file:
            cmd_rm += "; rm -rf %s" % tmp_file
        session.cmd_output_safe(cmd_rm)
        process.system(cmd_rm, ignore_status=True)
        if host_vsock_session.is_alive():
            host_vsock_session.close()
        session.close()

    vm = env.get_vm(params["main_vm"])
    tmp_file = "/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)
    session = vm.wait_for_login()
    # TODO: Close selinux as temporary workaround for qemu bug 1656738
    # should be removed when fixed
    session.cmd_output("setenforce 0")
    nc_vsock_bin = compile_nc_vsock(test, vm, session)
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    port = random.randrange(1, 6000)
    nc_vsock_listen(nc_vsock_bin, port, session)
    host_vsock_session = nc_vsock_connect(nc_vsock_bin, guest_cid, port)
    connected_str = r"Connection from cid*"
    send_data = "Hello world"
    check_received_data(test, session, connected_str)
    error_context.context('Input "Hello world" to vsock.', logging.info)
    host_vsock_session.sendline(send_data)
    check_received_data(test, session, send_data)
    host_vsock_session.close()
    check_guest_nc_vsock_exit(test, session, close_session=True)

    # Transfer data from guest to host
    session = vm.wait_for_login()
    rec_session = send_data_from_guest_to_host(session, nc_vsock_bin,
                                               guest_cid, tmp_file)
    utils_misc.wait_for(lambda: not rec_session.is_alive(), timeout=20)
    check_guest_nc_vsock_exit(test, session)
    cmd_chksum = 'md5sum %s' % tmp_file
    md5_origin = session.cmd_output(cmd_chksum).split()[0]
    md5_received = process.system_output(cmd_chksum).split()[0].decode()
    if md5_received != md5_origin:
        clean(tmp_file)
        test.fail('Data transfer not integrated, the original md5 value'
                  ' is %s, while the md5 value received on host is %s' %
                  (md5_origin, md5_received))
    clean(tmp_file)
