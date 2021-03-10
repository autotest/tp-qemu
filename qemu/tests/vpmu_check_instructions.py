import os
import logging
import re

from shutil import copyfile

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import arch
from virttest import utils_package


@error_context.context_aware
def run(test, params, env):
    """
    vpum cpu cycles checking between host and guest:
    1) boot guest
    2) check cpu cycles for host
    3) check cpu cycles for guest and compare with host

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    tmp_dir = params.get("tmp_dir")
    timeout = params.get_numeric("login_timeout", 360)
    test_cmd = params.get("test_cmd")
    build_cmd = params.get("build_cmd")
    vm_arch = params["vm_arch_name"]
    host_arch = arch.ARCH
    src_dir = os.path.join(data_dir.get_deps_dir(), 'million')
    src_file = os.path.join(src_dir, "million-%s.s" % host_arch)
    dst_file = os.path.join(tmp_dir, "million-%s.s" % host_arch)

    if not utils_package.package_install("perf"):
        test.error("Install dependency packages failed")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    error_context.context("build binary file 'million' in host", logging.info)
    copyfile(src_file, dst_file)
    s, o = process.getstatusoutput(build_cmd % host_arch)
    if s:
        test.fail("Failed to build test command")

    error_context.context("running test command in host", logging.info)
    s, o = process.getstatusoutput(test_cmd)
    if s:
        test.fail("Failed to run test command")

    host_cpu_cycles = re.findall(r"(\d+) *instructions:u", o, re.M)

    if not utils_package.package_install("perf", session):
        test.error("Install dependency packages failed")
    src_file = os.path.join(src_dir, "million-%s.s" % vm_arch)
    error_context.context("transfer '%s' to guest('%s')" %
                          (src_file, dst_file), logging.info)
    vm.copy_files_to(src_file, tmp_dir, timeout=timeout)

    error_context.context("build binary file 'million' in guest", logging.info)
    session.cmd(build_cmd % vm_arch)

    error_context.context("running test command in guest", logging.info)
    output = session.cmd_output(test_cmd, timeout=timeout)
    guest_cpu_cycles = re.findall(r"(\d+) *instructions:u", output, re.M)
    if host_cpu_cycles != guest_cpu_cycles:
        test.fail("cpu cycles is different between host and guest ")
