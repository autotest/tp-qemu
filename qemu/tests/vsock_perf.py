import os
import time
import threading

from avocado.utils import process

from virttest import data_dir
from virttest import error_context


def copy_compile_testsuite(test, vm, session):
    """
    Download and compile upstream test suite on guest and host.

    :param test: QEMU test object
    ::param vm: Object qemu_vm.VM
    :param session: Guest session object
    """
    vsock_test_base_dir = "/home/"
    vsock_test_src_file = os.path.join(
        data_dir.get_deps_dir("vsock_test"),
        "vsock_test.tar.xz")

    rm_cmd = "rm -rf %s" % os.path.join(vsock_test_base_dir, "vsock*")
    process.system(rm_cmd, shell=True, ignore_status=True)
    session.cmd(rm_cmd, ignore_all_errors=True)
    cp_cmd = "cp %s %s" % (vsock_test_src_file, vsock_test_base_dir)
    process.system(cp_cmd, shell=True)
    vm.copy_files_to(vsock_test_src_file, vsock_test_base_dir)
    uncompress_cmd = "cd %s && tar zxf %s" % (
        vsock_test_base_dir, "vsock_test.tar.xz")
    process.system(uncompress_cmd, shell=True, ignore_status=True)
    session.cmd(uncompress_cmd)
    compile_cmd = "cd %s && make vsock_perf" % (os.path.join(
        vsock_test_base_dir, "vsock/"))
    host_status = process.system(compile_cmd, shell=True)
    guest_status = session.cmd_status(compile_cmd)
    if (host_status or guest_status) != 0:
        process.system(rm_cmd, shell=True, ignore_status=True)
        session.cmd_output_safe(rm_cmd, ignore_all_errors=True)
        session.close()
        test.error("Complile failed")
    return os.path.join(vsock_test_base_dir, "vsock/vsock_perf")


def run_host_cmd(host_cmd, host_file):
    status, host_output = process.getstatusoutput(
        host_cmd, timeout=30, shell=True)
    time.sleep(3)

    with open(host_file, 'a') as file:
        file.write(host_output + '\n')


@error_context.context_aware
def run(test, params, env):
    """
    Vsock_test suite

    1. Boot guest with vhost-vsock-pci device
    2. Disable firewall in guest
    3. Download and compile vsock_perf suite in guest and host
    4. Run vsock_perf test on both host and guest
    5. Collect performance data and save in result files

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    disable_firewall = params.get("disable_firewall")
    session.cmd(disable_firewall, ignore_all_errors=True)

    kernel_version = process.getoutput("uname -r", shell=True)
    test.log.info("Current kernel version: %s" % kernel_version)

    try:
        test_bin = copy_compile_testsuite(test, vm, session)
        test.log.info("test_bin: %s" % test_bin)
        host_file = params["host_file"] + kernel_version
        guest_file = params["guest_file"] + kernel_version

        host_cmd = params["host_cmd"]
        guest_cmd = params["guest_cmd"] % (params["host_cid"])
        for _ in range(params.get_numeric("repeate_times")):
            test.log.info("Start perf test from host ...")
            host_thread = threading.Thread(
                target=run_host_cmd, args=(
                    host_cmd, host_file))
            host_thread.start()
            time.sleep(5)
            test.log.info("Start perf test from guest ...")
            status, guest_output = session.cmd_status_output(guest_cmd)
            with open(guest_file, 'a') as file:
                file.write(guest_output + '\n')
            host_thread.join()
            test.log.info("loop number %s" % _)
            time.sleep(10)
            if status != 0:
                test.fail(
                    "vsock_perf test failed in guest. %s %s" %
                    (status, guest_output))

    finally:
        rm_cmd = "rm -rf /home/vsock*"
        process.system(rm_cmd, shell=True, timeout=10, ignore_status=True)
        session.cmd(rm_cmd, ignore_all_errors=True)
        session.close()
