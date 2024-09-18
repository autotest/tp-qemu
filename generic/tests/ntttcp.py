import glob
import os
import re

import aexpect
from avocado.utils import process
from virttest import error_context, utils_misc, utils_test

_receiver_ready = False


@error_context.context_aware
def _verify_vm_driver(vm, test, driver_name, timeout=360):
    """
    Verify driver for vm

    :param vm: target vm
    :param test: the current test
    :param driver: target driver name
    :param timeout: the timeout for the login and verify operation
    """

    error_context.context(
        "Check if driver is installed" " and verified for vm: %s" % vm.name,
        test.log.info,
    )
    session = vm.wait_for_login(timeout=timeout)
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_name, timeout
    )
    session.close()


def run(test, params, env):
    """
    Run NTttcp on Windows guest

    1) Install NTttcp in server/client side by Autoit
    2) Start NTttcp in server/client side
    3) Get test results

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    results_path = os.path.join(test.resultsdir, "raw_output_%s" % test.iteration)
    platform = "x86"
    if "64" in params["vm_arch_name"]:
        platform = "x64"
    buffers = params.get("buffers").split()
    buf_num = params.get("buf_num", 200000)
    session_num = params.get("session_num")
    timeout = int(params.get("timeout")) * int(session_num)
    driver_verifier = params["driver_verifier"]

    vm_sender = env.get_vm(params["main_vm"])
    vm_sender.verify_alive()
    # verify driver
    _verify_vm_driver(vm_sender, test, driver_verifier)

    test.log.debug(process.system("numactl --hardware", ignore_status=True, shell=True))
    test.log.debug(process.system("numactl --show", ignore_status=True, shell=True))
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    if params.get("numa_node"):
        numa_node = int(params.get("numa_node"))
        node = utils_misc.NumaNode(numa_node)
        utils_test.qemu.pin_vm_threads(vm_sender, node)

    vm_receiver = env.get_vm("vm2")
    vm_receiver.verify_alive()
    _verify_vm_driver(vm_receiver, test, driver_verifier)
    sess = None
    try:
        sess = vm_receiver.wait_for_login(timeout=login_timeout)
        receiver_addr = vm_receiver.get_address()
        if not receiver_addr:
            test.error("Can't get receiver(%s) ip address" % vm_receiver.name)
        if params.get("numa_node"):
            utils_test.qemu.pin_vm_threads(vm_receiver, node)
    finally:
        if sess:
            sess.close()

    @error_context.context_aware
    def install_ntttcp(session):
        """Install ntttcp through a remote session"""
        test.log.info("Installing NTttcp ...")
        try:
            # Don't install ntttcp if it's already installed
            error_context.context("NTttcp directory already exists")
            session.cmd(params.get("check_ntttcp_cmd"))
        except aexpect.ShellCmdError:
            ntttcp_install_cmd = params.get("ntttcp_install_cmd")
            ntttcp_install_cmd = utils_misc.set_winutils_letter(
                session, ntttcp_install_cmd
            )
            error_context.context("Installing NTttcp on guest")
            session.cmd(ntttcp_install_cmd % (platform, platform), timeout=200)

    def receiver():
        """Receive side"""
        test.log.info("Starting receiver process on %s", receiver_addr)
        session = vm_receiver.wait_for_login(timeout=login_timeout)
        install_ntttcp(session)
        ntttcp_receiver_cmd = params.get("ntttcp_receiver_cmd")
        global _receiver_ready
        f = open(results_path + ".receiver", "a")
        for b in buffers:
            utils_misc.wait_for(lambda: not _wait(), timeout)
            _receiver_ready = True
            rbuf = params.get("fixed_rbuf", b)
            cmd = ntttcp_receiver_cmd % (session_num, receiver_addr, rbuf, buf_num)
            r = session.cmd_output(cmd, timeout=timeout, print_func=test.log.debug)
            f.write("Send buffer size: %s\n%s\n%s" % (b, cmd, r))
        f.close()
        session.close()

    def _wait():
        """Check if receiver is ready"""
        global _receiver_ready
        if _receiver_ready:
            return _receiver_ready
        return False

    def sender():
        """Send side"""
        test.log.info("Sarting sender process ...")
        session = vm_sender.wait_for_serial_login(timeout=login_timeout)
        install_ntttcp(session)
        ntttcp_sender_cmd = params.get("ntttcp_sender_cmd")
        f = open(results_path + ".sender", "a")
        try:
            global _receiver_ready
            for b in buffers:
                cmd = ntttcp_sender_cmd % (session_num, receiver_addr, b, buf_num)
                # Wait until receiver ready
                utils_misc.wait_for(_wait, timeout)
                r = session.cmd_output(cmd, timeout=timeout, print_func=test.log.debug)
                _receiver_ready = False
                f.write("Send buffer size: %s\n%s\n%s" % (b, cmd, r))
        finally:
            f.close()
            session.close()

    def parse_file(resultfile):
        """Parse raw result files and generate files with standard format"""
        fileobj = open(resultfile, "r")
        lst = []
        found = False
        for line in fileobj.readlines():
            o = re.findall(r"Send buffer size: (\d+)", line)
            bfr = ""
            if o:
                bfr = o[0]
            if "Total Throughput(Mbit/s)" in line:
                found = True
            if found:
                fields = line.split()
                if len(fields) == 0:
                    continue
                try:
                    [float(i) for i in fields]
                    lst.append([bfr, fields[-1]])
                except ValueError:
                    continue
                found = False
        return lst

    try:
        bg = utils_misc.InterruptedThread(receiver, ())
        bg.start()
        if bg.is_alive():
            sender()
            bg.join(suppress_exception=True)
        else:
            test.error("Can't start backgroud receiver thread")
    finally:
        for i in glob.glob("%s.receiver" % results_path):
            f = open("%s.RHS" % results_path, "w")
            raw = "  buf(k)| throughput(Mbit/s)"
            test.log.info(raw)
            f.write(
                "#ver# %s\n#ver# host kernel: %s\n"
                % (
                    process.system_output(
                        "rpm -q qemu-kvm", shell=True, verbose=False, ignore_status=True
                    ),
                    os.uname()[2],
                )
            )
            desc = """#desc# The tests are sessions of "NTttcp", send buf"
" number is %s. 'throughput' was taken from ntttcp's report.
#desc# How to read the results:
#desc# - The Throughput is measured in Mbit/sec.
#desc#
""" % (buf_num)
            f.write(desc)
            f.write(raw + "\n")
            for j in parse_file(i):
                raw = "%8s| %8s" % (j[0], j[1])
                test.log.info(raw)
                f.write(raw + "\n")
            f.close()
