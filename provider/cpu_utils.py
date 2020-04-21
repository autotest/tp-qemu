import re
import logging

from virttest import utils_misc
from virttest.utils_test import VMStress, StressError


class VMStressBinding(VMStress):
    """
    Run stress tool on VMs, and bind the process to the specified cpu
    """
    def __init__(self, vm, params, stress_args=""):
        super(VMStressBinding, self).__init__(vm, "stress", params,
                                              stress_args=stress_args)
        self.install()

    def load_stress_tool(self, cpu_id):
        """
        Load the stress tool and bind it to the specified CPU

        :param cpu_id: CPU id you want to bind
        """
        cmd = "setsid taskset -c {} {} {} > /dev/null".format(cpu_id,
                                                              self.stress_cmds,
                                                              self.stress_args)
        logging.info("Launch stress with command: %s", cmd)
        self.cmd_launch(cmd)
        # wait for stress to start and then check, if not raise StressError
        if not utils_misc.wait_for(self.app_running,
                                   self.stress_wait_for_timeout,
                                   first=2.0, step=1.0,
                                   text="wait for stress app to start"):
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
    return set(map(int, re.findall(r"processor\s+(?::\s)?(\d+)",
                                   output, re.M)))


def check_guest_cpu_topology(session, os_type, cpuinfo):
    """
    check the cpu topology of the guest.

    :param session: session Object
    :param os_type: guest os type, windows or linux
    :param cpuinfo: virt_vm.CpuInfo Object
    :return: True if guest topology is same as we expected
    """
    if os_type == "linux":
        out = session.cmd_output_safe("lscpu")
        cpu_info = dict(re.findall(r"([A-Z].+):\s+(.+)", out, re.M))
        sockets = int(cpu_info["Socket(s)"])
        cores = int(cpu_info["Core(s) per socket"])
        threads = int(cpu_info["Thread(s) per core"])
    else:
        cmd = ('powershell "Get-WmiObject Win32_processor | Format-List '
               'NumberOfCores,ThreadCount"')
        out = session.cmd_output_safe(cmd).strip()
        try:
            cpu_info = [dict(re.findall(r"(\w+)\s+:\s(\d+)", cpu_out, re.M))
                        for cpu_out in out.split("\n\n")]
            sockets = len(cpu_info)
            cores = int(cpu_info[0]["NumberOfCores"])
            threads = int(cpu_info[0]["ThreadCount"])
        except KeyError:
            logging.warning("Attempt to get output via 'powershell' failed, "
                            "output returned by guest:\n%s", out)
            logging.info("Try again via 'wmic'")
            cmd = 'wmic CPU get NumberOfCores,ThreadCount /Format:list'
            out = session.cmd_output_safe(cmd).strip()
            try:
                cpu_info = [dict(re.findall(r"(\w+)=(\d+)", cpu_out, re.M))
                            for cpu_out in out.split("\n\n")]
                sockets = len(cpu_info)
                cores = int(cpu_info[0]["NumberOfCores"])
                threads = int(cpu_info[0]["ThreadCount"])
            except KeyError:
                logging.error("Attempt to get output via 'wmic' failed, output"
                              " returned by guest:\n%s", out)
                return False

    is_matched = (cpuinfo.sockets == sockets and cpuinfo.cores == cores and
                  cpuinfo.threads == threads)
    if not is_matched:
        logging.debug("CPU infomation of guest:\n%s", out)

    return is_matched
