import logging
import re

from avocado.utils import process
from virttest import utils_misc
from virttest.utils_test import StressError, VMStress
from virttest.utils_version import VersionInterval

LOG_JOB = logging.getLogger("avocado.test")


class VMStressBinding(VMStress):
    """
    Run stress tool on VMs, and bind the process to the specified cpu
    """

    def __init__(self, vm, params, stress_args=""):
        super(VMStressBinding, self).__init__(
            vm, "stress", params, stress_args=stress_args
        )
        self.install()

    def load_stress_tool(self, cpu_id):
        """
        Load the stress tool and bind it to the specified CPU

        :param cpu_id: CPU id you want to bind
        """
        cmd = "setsid taskset -c {} {} {} > /dev/null".format(
            cpu_id, self.stress_cmds, self.stress_args
        )
        LOG_JOB.info("Launch stress with command: %s", cmd)
        self.cmd_launch(cmd)
        # wait for stress to start and then check, if not raise StressError
        if not utils_misc.wait_for(
            self.app_running,
            self.stress_wait_for_timeout,
            first=2.0,
            step=1.0,
            text="wait for stress app to start",
        ):
            raise StressError("Stress does not running as expected.")


def get_guest_cpu_ids(session, os_type):
    """
    Get the ids of all CPUs of the guest

    :param session: ShellSession object of VM
    :param os_type: guest os type, windows or linux
    :return: list of cpu id
    """
    if os_type == "windows":
        # Windows can not get each core id of socket, so this function is
        # meaningless, directly returns an empty set
        return set()
    cmd = "grep processor /proc/cpuinfo"
    output = session.cmd_output(cmd)
    return set(map(int, re.findall(r"processor\s+(?::\s)?(\d+)", output, re.M)))


def check_if_vm_vcpu_topology_match(session, os_type, cpuinfo, test, devices=None):
    """
    check the cpu topology of the guest.

    :param session: session Object
    :param os_type: guest os type, windows or linux
    :param cpuinfo: virt_vm.CpuInfo Object
    :param test: QEMU test object
    :param devices: qcontainer.DevContainer Object
    :return: True if guest topology is same as we expected
    """
    if os_type == "linux":
        out = session.cmd_output_safe("lscpu")
        cpu_info = dict(re.findall(r"([A-Z].+):\s+(.+)", out, re.M))
        if str(cpu_info["Architecture"]) == "s390x":
            sockets = int(cpu_info["Socket(s) per book"])
        else:
            sockets = int(cpu_info["Socket(s)"])
        cores = int(cpu_info["Core(s) per socket"])
        threads = int(cpu_info["Thread(s) per core"])
        threads_matched = cpuinfo.threads == threads
    else:
        cmd = (
            'powershell "Get-WmiObject Win32_processor | Format-List '
            'NumberOfCores,ThreadCount"'
        )
        out = session.cmd_output_safe(cmd).strip()
        try:
            cpu_info = [
                dict(re.findall(r"(\w+)\s+:\s(\d+)", cpu_out, re.M))
                for cpu_out in out.split("\n\n")
            ]
            sockets = len(cpu_info)
            cores = int(cpu_info[0]["NumberOfCores"])
            threads = int(cpu_info[0]["ThreadCount"])
        except KeyError:
            LOG_JOB.warning(
                "Attempt to get output via 'powershell' failed, "
                "output returned by guest:\n%s",
                out,
            )
            LOG_JOB.info("Try again via 'wmic'")
            cmd = "wmic CPU get NumberOfCores,ThreadCount /Format:list"
            out = session.cmd_output_safe(cmd).strip()
            try:
                cpu_info = [
                    dict(re.findall(r"(\w+)=(\d+)", cpu_out, re.M))
                    for cpu_out in out.split("\n\n")
                ]
                sockets = len(cpu_info)
                cores = int(cpu_info[0]["NumberOfCores"])
                threads = int(cpu_info[0]["ThreadCount"])
            except KeyError:
                LOG_JOB.error(
                    "Attempt to get output via 'wmic' failed, output"
                    " returned by guest:\n%s",
                    out,
                )
                return False
        if devices:
            # Until QEMU 8.1 there was a different behaviour for thread count in case
            # of Windows guests. It represented number of threads per single core, not
            # the total number of threads available for all cores in socket. Therefore
            # we disable check for older QEMU versions and adjust for newer versions.
            if devices.qemu_version in VersionInterval("[, 8.1.0)"):
                LOG_JOB.warning("ThreadCount is disabled for Windows guests")
                threads_matched = True
            else:
                threads_matched = threads // cores == cpuinfo.threads
        else:
            test.fail("Variable 'devices' must be defined for Windows guest.")

    is_matched = (
        cpuinfo.sockets == sockets and cpuinfo.cores == cores and threads_matched  # pylint: disable=E0606
    )

    if not is_matched:
        LOG_JOB.debug("CPU infomation of guest:\n%s", out)

    return is_matched


def check_cpu_flags(params, flags, test, session=None):
    """
    Check cpu flags on host or guest.(only for Linux now)
    :param params: Dictionary with the test parameters
    :param flags: checked flags
    :param test: QEMU test object
    :param session: guest session
    """
    cmd = "lscpu | grep Flags | awk -F ':'  '{print $2}'"
    func = process.getoutput
    if session:
        func = session.cmd_output
    out = func(cmd).split()
    missing = [f for f in flags.split() if f not in out]
    if session:
        LOG_JOB.info("Check cpu flags inside guest")
        if missing:
            test.fail("Flag %s not in guest" % missing)
        no_flags = params.get("no_flags")
        if no_flags:
            err_flags = [f for f in no_flags.split() if f in out]
            if err_flags:
                test.fail("Flag %s should not be present in guest" % err_flags)
    else:
        LOG_JOB.info("Check cpu flags on host")
        if missing:
            test.cancel("This host doesn't support flag %s" % missing)


# Copied from unstable module "virttest/cpu.py"
def check_if_vm_vcpu_match(vcpu_desire, vm):
    """
    This checks whether the VM vCPU quantity matches the value desired.

    :param vcpu_desire: vcpu value to be checked
    :param vm: VM Object

    :return: Boolean, True if actual vcpu value matches with vcpu_desire
    """
    vcpu_actual = vm.get_cpu_count("cpu_chk_cmd")
    if isinstance(vcpu_desire, str) and vcpu_desire.isdigit():
        vcpu_desire = int(vcpu_desire)
    if vcpu_desire != vcpu_actual:
        LOG_JOB.debug(
            "CPU quantity mismatched !!! guest said it got %s " "but we assigned %s",
            vcpu_actual,
            vcpu_desire,
        )
        return False
    LOG_JOB.info("CPU quantity matched: %s", vcpu_actual)
    return True


def check_if_vm_vcpus_match_qemu(vm):
    vcpus_count = vm.params.get_numeric("vcpus_count", 1)
    vcpu_devices = vm.params.objects("vcpu_devices")
    enabled_vcpu_devices = []

    for vcpu_device in vcpu_devices:
        vcpu_params = vm.params.object_params(vcpu_device)
        if vcpu_params.get_boolean("vcpu_enable"):
            enabled_vcpu_devices.append(vcpu_device)
    enabled_count = vm.cpuinfo.smp + (len(enabled_vcpu_devices) * vcpus_count)

    return check_if_vm_vcpu_match(enabled_count, vm)
