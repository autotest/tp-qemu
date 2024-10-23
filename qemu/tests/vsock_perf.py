import os
import platform
import shutil
import time

import aexpect
from avocado.core import exceptions
from avocado.utils import process
from virttest import data_dir, error_context


def copy_compile_testsuite(vm, vsock_test_base_dir, session):
    vsock_test_src_file = os.path.join(
        data_dir.get_deps_dir("vsock_test"), "vsock_test.tar.xz"
    )

    shutil.copy2(vsock_test_src_file, vsock_test_base_dir)
    vm.copy_files_to(vsock_test_src_file, vsock_test_base_dir)

    uncompress_cmd = "cd %s && tar zxf %s" % (vsock_test_base_dir, "vsock_test.tar.xz")
    process.system(uncompress_cmd, shell=True, ignore_status=True)
    session.cmd(uncompress_cmd)
    compile_cmd = "cd %s && make vsock_perf" % (
        os.path.join(vsock_test_base_dir, "vsock/")
    )
    host_status = process.system(compile_cmd, shell=True)
    guest_status = session.cmd_status(compile_cmd)

    if host_status or guest_status:
        raise exceptions.TestError("Test suite compile failed.")

    return os.path.join(vsock_test_base_dir, "vsock/vsock_perf")


def cleanup(directory, session):
    rm_cmd = f"rm -rf {os.path.join(directory, 'vsock*')}"
    process.system(rm_cmd, shell=True, ignore_status=True)
    session.cmd(rm_cmd, ignore_all_errors=True)


@error_context.context_aware
def run(test, params, env):
    """
    Vsock_perf test

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

    kernel_version = platform.uname().release
    vsock_test_base_dir = "/home/"

    try:
        test_bin = copy_compile_testsuite(vm, vsock_test_base_dir, session)
        test.log.info("test_bin: %s", test_bin)

        host_file = params["host_file"] + kernel_version
        guest_file = params["guest_file"] + kernel_version
        host_cmd = params["host_cmd"]
        guest_cmd = params["guest_cmd"]

        for _ in range(params.get_numeric("repeate_times")):
            test.log.info("Start perf test from host ...")
            host_output = aexpect.run_bg(host_cmd, timeout=30)
            time.sleep(3)
            test.log.info("Start perf test from guest ...")
            guest_status, guest_output = session.cmd_status_output(guest_cmd)

            with open(host_file, "a") as file:
                file.write(host_output.get_output() + "\n")
            with open(guest_file, "a") as file:
                file.write(guest_output + "\n")
            test.log.info("loop number %s", _)

            host_status = host_output.get_status()
            host_output.close()

            if host_status or guest_status:
                test.fail("vsock_perf test failed")

    finally:
        cleanup(vsock_test_base_dir, session)
        session.close()
