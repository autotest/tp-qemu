import logging
import os
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_test

from provider import pktgen_utils
from provider.vdpa_sim_utils import (
    VhostVdpaNetSimulatorTest,
    VirtioVdpaNetSimulatorTest,
)

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def run(test, params, env):
    """
    Pktgen tests multiple scenarios:
    default test steps:
        Run Pktgen test between host/guest
        1) Boot the main vm, or just grab it if it's already booted.
        2) Configure pktgen on guest or host
        3) Run tx/rx test on the VM
        4) Finish when timeout
    vp_vdpa_test_vm test steps:
        Run Pktgen test between host/guest with vp_vdpa module
        1) Boot the main vm, or just grab it if it's already booted.
        2) Unbind virtio pci device
        3) Bind the pci device  to vp_vdpa module
        3) Run tx/rx test on the VM
        4) Finish when timeout
    vhost_sim_test_vm test steps:
        1) Setup vdpa simulator ENV and create vhost-vdpa devices.
        2) Boot vm and run pktgen test on VM
        3) Destroy vm, vhost-vdpa devices and vdpa simulator ENV
    virtio_sim_test_host test steps:
        1) Setup vdpa simulator env and create virtio vdpa devices
        2) run pktgen test on host
        3) Destroy virtio vdpa devices and vdpa simulator env

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _pin_vm_threads(node):
        """
        pin guest vcpu and vhost threads to cpus of a numa node repectively

        :param node: which numa node to pin
        """
        if node:
            if not isinstance(node, utils_misc.NumaNode):
                node = utils_misc.NumaNode(int(node))
            utils_test.qemu.pin_vm_threads(vm, node)

    def init_vm_and_login(test, params, env, result_file, pktgen_runner):
        error_context.context("Init the VM, and try to login", test.log.info)
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session_serial = vm.wait_for_serial_login(restart_network=True)
        # print numa information on host and pinning vhost and vcpus to cpus
        process.system_output("numactl --hardware")
        process.system_output("numactl --show")
        _pin_vm_threads(params.get("numa_node"))
        guest_ver = session_serial.cmd_output(guest_ver_cmd)
        result_file.write("### guest-kernel-ver :%s" % guest_ver)

        if pktgen_runner.is_version_lt_rhel7(session_serial.cmd("uname -r")):
            if guest_ver.count("64k"):
                pktgen_runner.install_package(
                    guest_ver.strip(),
                    pagesize="64k",
                    vm=vm,
                    session_serial=session_serial,
                )
            else:
                pktgen_runner.install_package(
                    guest_ver.strip(), vm=vm, session_serial=session_serial
                )
        return vm, session_serial

    # get parameter from dictionary
    kvm_ver_chk_cmd = params.get("kvm_ver_chk_cmd")
    guest_ver_cmd = params["guest_ver_cmd"]
    disable_iptables_rules_cmd = params.get("disable_iptables_rules_cmd")
    test_vm = params.get_boolean("test_vm")
    vdpa_test = params.get_boolean("vdpa_test")
    vp_vdpa = params.get_boolean("vp_vdpa")

    # get qemu, kvm version info and write them into result
    result_path = utils_misc.get_path(test.resultsdir, "pktgen_perf.RHS")
    result_file = open(result_path, "w")
    kvm_ver = process.system_output(kvm_ver_chk_cmd, shell=True).decode()
    host_ver = os.uname()[2]
    result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
    result_file.write("### kvm_version : %s\n" % host_ver)

    if disable_iptables_rules_cmd:
        error_context.context("disable iptables rules on host")
        process.system(disable_iptables_rules_cmd, shell=True)

    pktgen_runner = pktgen_utils.PktgenRunner()
    if pktgen_runner.is_version_lt_rhel7(process.getoutput("uname -r")):
        if host_ver.count("64k"):
            pktgen_runner.install_package(host_ver, pagesize="64k")
        else:
            pktgen_runner.install_package(host_ver)

    vdpa_net_test = None
    vm = None
    try:
        if vdpa_test and not test_vm:
            vdpa_net_test = VirtioVdpaNetSimulatorTest()
            vdpa_net_test.setup()
            interface = vdpa_net_test.add_dev(params.get("netdst"), params.get("mac"))
            LOG_JOB.info("The virtio_vdpa device name is: '%s'", interface)
            LOG_JOB.info("Test virtio_vdpa with the simulator on the host")
            pktgen_utils.run_tests_for_category(
                params, result_file, interface=interface
            )
        elif vdpa_test and test_vm:
            vdpa_net_test = VhostVdpaNetSimulatorTest()
            vdpa_net_test.setup()
            dev = vdpa_net_test.add_dev(
                params.get("netdst_nic2"), params.get("mac_nic2")
            )
            LOG_JOB.info("The vhost_vdpa device name is: '%s'", dev)
            LOG_JOB.info("Test vhost_vdpa with the simulator on the vm")
            process.system_output("cat /sys/module/vdpa_sim/parameters/use_va")
            vm, session_serial = init_vm_and_login(
                test, params, env, result_file, pktgen_runner
            )
            pktgen_utils.run_tests_for_category(
                params, result_file, test_vm, vm, session_serial
            )
        elif not vdpa_test:
            vm, session_serial = init_vm_and_login(
                test, params, env, result_file, pktgen_runner
            )
            if vp_vdpa:
                pktgen_utils.run_tests_for_category(
                    params, result_file, test_vm, vm, session_serial, vp_vdpa
                )
            else:
                pktgen_utils.run_tests_for_category(
                    params, result_file, test_vm, vm, session_serial
                )
    finally:
        if test_vm:
            vm.verify_kernel_crash()
            session_serial.close()
            utils_misc.verify_dmesg()
            vm.destroy()
        result_file.close()
        if vdpa_net_test:
            time.sleep(5)
            vdpa_net_test.remove_dev(params.get("netdst_nic2"))
            vdpa_net_test.cleanup()
        error_context.context(
            "Verify Host and guest kernel no error" "and call trace", test.log.info
        )
