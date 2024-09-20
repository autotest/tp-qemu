import os
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_net


def copy_compile_testsuite(test, vm, session):
    """
    Download and compile upstream test suite on guest and host.

    :param test: QEMU test object
    ::param vm: Object qemu_vm.VM
    :param session: Guest session object
    """
    vsock_test_base_dir = "/home/"
    vsock_test_src_file = os.path.join(
        data_dir.get_deps_dir("vsock_test"), "vsock_test.tar.xz"
    )
    rm_cmd = "rm -rf %s" % os.path.join(vsock_test_base_dir, "vsock*")
    process.system(rm_cmd, shell=True, ignore_status=True)
    session.cmd(rm_cmd, ignore_all_errors=True)
    cp_cmd = "cp %s %s" % (vsock_test_src_file, vsock_test_base_dir)
    process.system(cp_cmd, shell=True)
    vm.copy_files_to(vsock_test_src_file, vsock_test_base_dir)
    uncompress_cmd = "cd %s && tar zxf %s" % (vsock_test_base_dir, "vsock_test.tar.xz")
    process.system(uncompress_cmd, shell=True, ignore_status=True)
    session.cmd(uncompress_cmd)
    compile_cmd = "cd %s && make vsock_test" % os.path.join(
        vsock_test_base_dir, "vsock/"
    )
    host_status = process.system(compile_cmd, shell=True)
    guest_status = session.cmd_status(compile_cmd)
    if (host_status or guest_status) != 0:
        process.system(rm_cmd, shell=True, ignore_status=True)
        session.cmd_output_safe(rm_cmd, ignore_all_errors=True)
        session.close()
        test.error("vsocke_test complile failed")
    return os.path.join(vsock_test_base_dir, "vsock/vsock_test")


@error_context.context_aware
def run(test, params, env):
    """
    Vsock_test suite

    1. Boot guest with vhost-vsock-pci device
    2. Disable firewall in guest
    3. Download and compile upstream test suite in guest and host
    4. Run test suite

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    host_ip = utils_net.get_host_ip_address(params)
    guest_ip = vm.get_address()

    disable_firewall = params.get("disable_firewall")
    session.cmd(disable_firewall, ignore_all_errors=True)

    vsock_dev = params["vsocks"]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    host_cid = params["host_cid"]
    port = utils_misc.find_free_port()

    try:
        test_bin = copy_compile_testsuite(test, vm, session)

        # Scenario I: host = client, guest = server
        test.log.info("Host as client, guest as server...")
        client_cmd = params["client_cmd"] % (test_bin, guest_ip, port, guest_cid)
        server_cmd = params["server_cmd"] % (test_bin, port, host_cid)
        session.sendline(server_cmd)
        time.sleep(5)
        status, output = process.getstatusoutput(client_cmd, timeout=30, shell=True)
        if status != 0:
            test.fail("Test fail %s %s" % (status, output))
        test.log.info("command output: %s", output)

        try:
            session.read_up_to_prompt(timeout=10)
        except aexpect.ExpectTimeoutError:
            test.fail("server_cmd inside guest dosn't closed after test execution.")

        # Scenario II: host = server, guest = client
        test.log.info("Host as server, guest as client...")
        client_cmd = params["client_cmd"] % (test_bin, host_ip, port, host_cid)
        server_cmd = params["server_cmd"] % (test_bin, port, guest_cid)
        aexpect.Expect(
            server_cmd,
            auto_close=False,
            output_func=utils_misc.log_line,
            output_params=("vsock_%s_%s" % (guest_cid, port),),
        )
        time.sleep(5)
        status, output = session.cmd_status_output(client_cmd)
        if status != 0:
            test.fail("Test fail %s %s" % (status, output))
        test.log.info("command output: %s", output)
    finally:
        rm_cmd = "rm -rf /home/vsock*"
        process.system(rm_cmd, shell=True, timeout=10, ignore_status=True)
        session.cmd(rm_cmd, ignore_all_errors=True)
        session.close()
