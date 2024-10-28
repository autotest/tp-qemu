import logging
import os
import re
import time

import aexpect
import six
from avocado.utils import process
from virttest import data_dir, utils_misc, utils_net

LOG_JOB = logging.getLogger("avocado.test")


class PktgenConfig:
    def __init__(self, interface=None, dsc=None, runner=None):
        self.interface = interface
        self.dsc = dsc
        self.runner = runner

    def vp_vdpa_bind(self, session_serial):
        try:
            LOG_JOB.info("Starting the binding process for Virtio 1.0 network devices.")
            pci_list = utils_misc.get_pci_id_using_filter(
                "Virtio 1.0 network", session_serial
            )
            if not pci_list:
                raise ValueError("No PCI devices found matching 'Virtio 1.0 network'.")

            pci_id = utils_misc.get_full_pci_id(pci_list[0], session_serial)

            utils_misc.unbind_device_driver(pci_id, session_serial)
            LOG_JOB.debug("Device %s unbound from its current driver", pci_id)
            session_serial.cmd("modprobe vp_vdpa && modprobe virtio_vdpa")
            LOG_JOB.debug("vp_vdpa and virtio_vdpa modules loaded")

            # Re-bind device to vp-vdpa
            utils_misc.bind_device_driver(pci_id, "vp-vdpa", session_serial)
            LOG_JOB.debug("Device %s bound to vp-vdpa driver", pci_id)

            # Add vDPA device
            vdpa_cmd = "vdpa dev add name vdpa0 mgmtdev pci/%s" % pci_id
            session_serial.cmd(vdpa_cmd)

            LOG_JOB.debug("vDPA device added successfully")
            time.sleep(5)
            cmd = "vdpa dev list"
            output = session_serial.cmd_output_safe(cmd)
            if "vdpa0" not in output:
                raise ValueError(
                    "vDPA device 'vdpa0' not found in 'vdpa dev list' output"
                )
        except Exception as err:
            LOG_JOB.error("Error during vDPA binding process: %s", err)

    def configure_pktgen(
        self,
        params,
        script,
        pkt_cate,
        test_vm,
        vm=None,
        session_serial=None,
        interface=None,
    ):
        local_path = os.path.join(data_dir.get_shared_dir(), "scripts/pktgen_perf")
        remote_path = "/tmp/"

        if pkt_cate == "tx":
            LOG_JOB.info("test guest tx pps performance")
            vm.copy_files_to(local_path, remote_path)
            guest_mac = vm.get_mac_address(0)
            self.interface = utils_net.get_linux_ifname(session_serial, guest_mac)
            dsc_dev = utils_net.Interface(vm.get_ifname(0))
            self.dsc = dsc_dev.get_mac()
            self.runner = session_serial.cmd
        elif pkt_cate == "rx":
            LOG_JOB.info("test guest rx pps performance")
            process.run("cp -r %s %s" % (local_path, remote_path))
            host_bridge = params.get("netdst", "switch")
            utils_net.Interface(host_bridge)
            if script == "pktgen_perf":
                self.dsc = vm.wait_for_get_address(0, timeout=5)
            else:
                self.dsc = vm.get_mac_address(0)
            self.interface = vm.get_ifname(0)
            self.runner = process.system_output
        elif pkt_cate == "loopback":
            if test_vm:
                LOG_JOB.info("test guest loopback pps performance")
                vm.copy_files_to(local_path, remote_path)
                guest_mac = vm.get_mac_address(1)
                self.interface = utils_net.get_linux_ifname(session_serial, guest_mac)
                self.dsc = vm.get_mac_address(1)
                self.runner = session_serial.cmd
            elif not test_vm:
                LOG_JOB.info("test loopback pps performance on host")
                process.run("cp -r %s %s" % (local_path, remote_path))
                self.interface = interface
                self.dsc = params.get("mac")
                self.runner = process.system_output
        return self

    def generate_pktgen_cmd(
        self,
        script,
        pkt_cate,
        interface,
        dsc,
        threads,
        size,
        burst,
        session_serial=None,
    ):
        script_path = "/tmp/pktgen_perf/%s.sh" % script
        if script in "pktgen_perf":
            dsc_option = "-m" if pkt_cate == "tx" else "-d"
            cmd = "%s -i %s %s %s -t %s -s %s" % (
                script_path,
                interface,
                dsc_option,
                dsc,
                threads,
                size,
            )
        else:
            cmd = "%s -i %s -m %s -n 0 -t %s -s %s -b %s -c 0" % (
                script_path,
                interface,
                dsc,
                threads,
                size,
                burst,
            )

        if (
            session_serial
            and hasattr(self.runner, "__name__")
            and self.runner.__name__ == session_serial.cmd.__name__
        ):
            cmd += " &"

        return cmd


class PktgenRunner:
    def run_test(self, script, cmd, runner, interface, timeout):
        """
        Run pktgen  script on remote and gather packet numbers/time and
        calculate mpps.
        :param script: pktgen script name.
        :param cmd: The command to execute the pktgen script
        :param runner: The command runner function
        :param interface: The network interface used by pktgen.
        :param timeout: The maximum time allowed for the test to run
        :return: The calculated MPPS (Million Packets Per Second)
        """

        packets = "cat /sys/class/net/%s/statistics/tx_packets" % interface
        LOG_JOB.info("Start pktgen test by cmd '%s'", cmd)
        try:
            packet_b = runner(packets)
            packet_a = None
            runner(cmd, timeout)
        except aexpect.ShellTimeoutError:
            # when pktgen script is running on guest, the pktgen process
            # need to be killed.
            kill_cmd = (
                "kill -9 `ps -ef | grep %s --color | grep -v grep | "
                "awk '{print $2}'`" % script
            )
            runner(kill_cmd)
            packet_a = runner(packets)
        except process.CmdError:
            # when pktgen script is running on host, the pktgen process
            # will be quit when timeout triggers, so no need to kill it.
            packet_a = runner(packets)
        count = int(packet_a) - int(packet_b)
        pps_results = count / timeout

        # convert pps to mpps
        power = 10**6
        mpps_results = float(pps_results) / float(power)
        mpps_results = "%.2f" % mpps_results
        return mpps_results

    def install_package(self, ver, pagesize=None, vm=None, session_serial=None):
        """Check module pktgen, install kernel-modules-internal package"""

        output_cmd = process.getoutput
        if pagesize:
            kernel_ver = "kernel-%s-modules-internal-%s" % (pagesize, ver.split("+")[0])
        else:
            kernel_ver = "kernel-modules-internal-%s" % ver
        cmd_download = "cd /tmp && brew download-build %s --rpm" % kernel_ver
        cmd_install = "cd /tmp && rpm -ivh  %s.rpm --force --nodeps" % kernel_ver
        output_cmd(cmd_download)
        cmd_clean = "rm -rf /tmp/%s.rpm" % kernel_ver
        if session_serial:
            output_cmd = session_serial.cmd_output
            local_path = "/tmp/%s.rpm" % kernel_ver
            remote_path = "/tmp/"
            vm.copy_files_to(local_path, remote_path)
        output_cmd(cmd_install)
        output_cmd(cmd_clean)

    def is_version_lt_rhel7(self, uname_str):
        ver = re.findall("el(\\d+)", uname_str)
        if ver:
            return int(ver[0]) > 7
        return False


def format_result(result, base, fbase):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """
    if isinstance(result, six.string_types):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    else:
        raise TypeError(f"unexpected result type: {type(result).__name__}")
    return value % result


def run_tests_for_category(
    params,
    result_file,
    test_vm=None,
    vm=None,
    session_serial=None,
    vp_vdpa=None,
    interface=None,
):
    """
    Run Pktgen tests for a specific category.
    :param params: Dictionary with the test parameters
    :param result_file: File to write the test results.
    :param test_vm: Flag indicating whether the test is running on a VM
    :param vm: VM instance
    :param session_serial: Session serial for VM
    :param interface: Network interface for the test
    """

    timeout = float(params.get("pktgen_test_timeout", "240"))
    category = params.get("category")
    params.get("pkt_size")
    params.get("pktgen_threads")
    burst = params.get("burst")
    record_list = params.get("record_list")
    pktgen_script = params.get("pktgen_script")
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    # get record_list
    record_line = ""
    for record in record_list.split():
        record_line += "%s|" % format_result(record, base, fbase)

    pktgen_config = PktgenConfig()
    pktgen_runner = PktgenRunner()
    if vp_vdpa:
        pktgen_config.vp_vdpa_bind(session_serial)

    for script in pktgen_script.split():
        for pkt_cate in category.split():
            result_file.write("Script:%s " % script)
            result_file.write("Category:%s\n" % pkt_cate)
            result_file.write("%s\n" % record_line.rstrip("|"))

            for size in params.get("pkt_size", "").split():
                for threads in params.get("pktgen_threads", "").split():
                    for burst in params.get("burst", "").split():
                        if pkt_cate != "loopback":
                            pktgen_config = pktgen_config.configure_pktgen(
                                params, script, pkt_cate, test_vm, vm, session_serial
                            )
                            exec_cmd = pktgen_config.generate_pktgen_cmd(
                                script,
                                pkt_cate,
                                pktgen_config.interface,
                                pktgen_config.dsc,
                                threads,
                                size,
                                burst,
                                session_serial,
                            )
                        else:
                            if not test_vm:
                                pktgen_config = pktgen_config.configure_pktgen(
                                    params,
                                    script,
                                    pkt_cate,
                                    test_vm,
                                    interface=interface,
                                )
                                exec_cmd = pktgen_config.generate_pktgen_cmd(
                                    script,
                                    pkt_cate,
                                    pktgen_config.interface,
                                    pktgen_config.dsc,
                                    threads,
                                    size,
                                    burst,
                                )
                            else:
                                pktgen_config = pktgen_config.configure_pktgen(
                                    params,
                                    script,
                                    pkt_cate,
                                    test_vm,
                                    vm,
                                    session_serial,
                                )
                                exec_cmd = pktgen_config.generate_pktgen_cmd(
                                    script,
                                    pkt_cate,
                                    pktgen_config.interface,
                                    pktgen_config.dsc,
                                    threads,
                                    size,
                                    burst,
                                    session_serial,
                                )
                        pkt_cate_r = pktgen_runner.run_test(
                            script,
                            exec_cmd,
                            pktgen_config.runner,
                            pktgen_config.interface,
                            timeout,
                        )

                        line = "%s|" % format_result(
                            size,
                            params.get("format_base", "12"),
                            params.get("format_fbase", "2"),
                        )
                        line += "%s|" % format_result(
                            threads,
                            params.get("format_base", "12"),
                            params.get("format_fbase", "2"),
                        )
                        line += "%s|" % format_result(
                            burst,
                            params.get("format_base", "12"),
                            params.get("format_fbase", "2"),
                        )
                        line += "%s" % format_result(
                            pkt_cate_r,
                            params.get("format_base", "12"),
                            params.get("format_fbase", "2"),
                        )
                        result_file.write(("%s\n" % line))
