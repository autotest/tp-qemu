"""
Module for sgx relevant operations.
"""

import logging
import re

from avocado.utils import process
from virttest.staging import utils_memory
from virttest.utils_misc import normalize_data_size

LOG_JOB = logging.getLogger("avocado.test")


class SGXError(Exception):
    """General SGX error"""

    pass


def _get_epc_size(output):
    """
    Get epc size from system message

    :param output: epc section info
    :return: total epc size
    """
    epc_size = 0
    for line in output.splitlines():
        tmp_epc = re.search(r"\b0x[0-9a-fA-F]*-0x[0-9a-fA-F]*\b", str(line))
        if tmp_epc:
            epc_size += (
                int(tmp_epc[0].split("-")[1], 16)
                - int(tmp_epc[0].split("-")[0], 16)
                + 1
            )
    return epc_size


class SGXHostCapability(object):
    """
    Hypervisor sgx capabilities check.
    """

    def __init__(self, test, params):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        """
        self._test = test
        self._params = params
        self.host_epc_size = 0

    def validate_sgx_cap(self):
        """
        Validate if host enable sgx
        """
        try:
            host_sgx_msg = process.system_output(
                "journalctl --boot|grep -i 'sgx: EPC section'", shell=True
            )
        except Exception as e:
            self._test.cancel("Host sgx capability check fail %s" % e)
        else:
            self.host_epc_size = _get_epc_size(host_sgx_msg)

    def validate_numa_node_count(self):
        """
        Validate if host numa nodes satisfy test requirement
        """
        LOG_JOB.debug("Check host's numa node(s)!")
        host_numa = utils_memory.numa_nodes()
        node_list = []
        numa_info = process.getoutput("numactl -H")
        for i in host_numa:
            node_size = re.findall(r"node %d size: " r"\d+ \w" % i, numa_info)[
                0
            ].split()[-2]
            if node_size != "0":
                node_list.append(str(i))
        monitor_expect_nodes = int(self._params["monitor_expect_nodes"])
        if len(node_list) < monitor_expect_nodes:
            self._test.cancel(
                "host numa nodes %s isn't enough for " "testing." % node_list
            )


class SGXChecker(object):
    """
    Basic verification on sgx capabilities for both host and guest.
    """

    def __init__(self, test, params, vm):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        :param vm:VM object.
        """
        self._test = test
        self._params = params
        self._vm = vm
        self._monitor = vm.monitor

    def verify_sgx_flags(self, qmp_command, flags):
        """
        Check if sgx cpu flags enabled in qmp cmd

        :param qmp_command: query sgx qmp command output
        :param flags: sgx flags need to be verified
        """
        for ele in flags:
            if qmp_command[ele] is not True:
                self._test.fail("%s is not enabled, qmp check failed." % ele)

    def get_config_total_epc_size(self):
        """
        Get total epc size from configuration.

        :return: total configured epc size
        """
        epc_list = self._params["vm_sgx_epc_devs"].split()
        config_epc_size = 0
        for ele in epc_list:
            epc_params = self._params.object_params(ele)
            ele_memdev = self._params.object_params(epc_params["vm_sgx_epc_memdev"])
            tmp_epc_size = int(
                float(normalize_data_size(ele_memdev["size_mem"], "B", 1024))
            )
            config_epc_size += tmp_epc_size
        return config_epc_size

    def get_config_epc_numa_info(self):
        """
        Get epc size on each nume node from configuration.

        :return: epc size on each nume node configured.
        """
        guest_sgx_epc_list = self._params["vm_sgx_epc_devs"].split()
        tmp_epc_dict = {}
        for ele in guest_sgx_epc_list:
            epc_params = self._params.object_params(ele)
            ele_memdev = self._params.object_params(epc_params["vm_sgx_epc_memdev"])
            tmp_epc_size = int(
                float(normalize_data_size(ele_memdev["size_mem"], "B", 1024))
            )
            epc_numa_id = int(epc_params["vm_sgx_epc_node"])
            tmp_epc_dict = {"size": tmp_epc_size, "node": epc_numa_id}
        return tmp_epc_dict

    def verify_qmp_host_sgx_cap(self, host_epc_size):
        """
        Verify query host sgx capabilities qmp cmd in sgx flags and epc size
        """
        sgx_flags = self._params["sgx_flags"].split()
        host_sgx_info = self._monitor.query_sgx_capabilities()
        self.verify_sgx_flags(host_sgx_info, sgx_flags)

        host_qmp_sections = host_sgx_info["sections"]
        host_qmp_section_size = 0
        for section in host_qmp_sections:
            host_qmp_section_size += int(section["size"])
        if host_epc_size != host_qmp_section_size:
            self._test.fail(
                "Host epc size %s is not equal to query sgx"
                "capabilities section size %s" % (host_epc_size, host_qmp_section_size)
            )
        LOG_JOB.debug("Guest query host capability verified successfully")

    def verify_qmp_guest_sgx_cap(self):
        """
        Verify query guest sgx capabilities qmp cmd in sgx flags and epc size
        """
        sgx_flags = self._params["sgx_flags"].split()
        guest_sgx_info = self._monitor.query_sgx()
        self.verify_sgx_flags(guest_sgx_info, sgx_flags)
        LOG_JOB.debug("Guest query SGX flags %s verified done", sgx_flags)

        epc_sections_info = guest_sgx_info["sections"]
        numa_epc_dict = self.get_config_epc_numa_info()
        if numa_epc_dict == epc_sections_info:
            self._test.fail(
                "Guest epc sized on each numa mis-matched, " "qmp check failed."
            )

        sgx_sections = guest_sgx_info["sections"]
        sgx_section_size = 0
        for section in sgx_sections:
            sgx_section_size += int(section["size"])
        config_epc_size = self.get_config_total_epc_size()
        if config_epc_size != sgx_section_size:
            self._test.fail(
                "Guest epc size %s is not equal to query_sgx"
                " section size %s" % (config_epc_size, sgx_section_size)
            )
        LOG_JOB.debug("Guest query SGX verified successfully")

    def verify_guest_epc_size(self, cmd_output):
        """
        Verify guest sgx epc size by cmd output

        :param cmd_output: get epc info cmd output.
        """
        guest_total_epc_size = self.get_config_total_epc_size()
        guest_msg_epc_size = _get_epc_size(cmd_output)
        if guest_msg_epc_size != int(guest_total_epc_size):
            self._test.fail(
                "Guest epc size %s is not equal to qemu set "
                "section size %s" % (guest_msg_epc_size, guest_total_epc_size)
            )
        LOG_JOB.debug("Guest SGX size verified successfully")
