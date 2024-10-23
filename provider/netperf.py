import logging
import os

from virttest import data_dir, utils_misc, utils_net, utils_netperf

LOG_JOB = logging.getLogger("avocado.test")


class NetperfTest(object):
    def __init__(self, params, vm):
        self.params = params
        self.vm = vm
        self.client = self.netperf_client()
        self.server = self.netperf_server(server_ip=params["netperf_server"])

    def netperf_client(self):
        """
        Init netperf client setup
        """
        self.client = utils_netperf.NetperfClient(
            self.vm.get_address(),
            self.params.get("netperf_client_path"),
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), self.params.get("netperf_client_bin")
            ),
            client=self.params.get("shell_client"),
            port=self.params.get("shell_port"),
            username=self.params.get("username"),
            password=self.params.get("password"),
            prompt=self.params.get("shell_prompt"),
            linesep=self.params.get("shell_linesep", "\n")
            .encode()
            .decode("unicode_escape"),
            status_test_command=self.params.get("status_test_command", ""),
            compile_option=self.params.get("compile_option", ""),
        )
        return self.client

    def netperf_server(self, server_ip="localhost", server_passwd=None):
        """
        Init netperf server setup
        """
        if server_ip == "localhost":
            server_ip = utils_net.get_host_ip_address(self.params)
            server_passwd = self.params.get("hostpassword")
        self.server = utils_netperf.NetperfServer(
            server_ip,
            self.params.get("server_path", "/var/tmp"),
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), self.params.get("netperf_server_link")
            ),
            password=server_passwd,
            compile_option=self.params.get("compile_option", ""),
        )
        return self.server

    def start_netperf_test(self):
        """
        Start netperf test between client and server
        """
        self.server.start()
        test_duration = self.params.get_numeric("netperf_test_duration", 120)
        netperf_output_unit = self.params.get("netperf_output_unit")
        extra_netperf_option = self.params.get("extra_netperf_option", "")
        test_protocols = self.params.get("test_protocol")
        extra_netperf_option += " -l %s" % test_duration
        if self.params.get("netperf_remote_cpu") == "yes":
            extra_netperf_option += " -C"
        elif self.params.get("netperf_local_cpu") == "yes":
            extra_netperf_option += " -c"
        if netperf_output_unit in "GMKgmk":
            extra_netperf_option += " -f %s" % netperf_output_unit
        option = "%s -t %s" % (extra_netperf_option, test_protocols)
        self.client.bg_start(
            utils_net.get_host_ip_address(self.params),
            option,
            self.params.get_numeric("netperf_para_sessions"),
            self.params.get("netperf_cmd_prefix", ""),
            package_sizes=self.params.get("netperf_sizes"),
        )
        if utils_misc.wait_for(self.netperf_status, 30, 0, 5):
            LOG_JOB.info("Netperf test start successfully.")
            return True
        else:
            LOG_JOB.info("Can not start netperf client.")
            return False

    def netperf_status(self):
        return self.client.is_netperf_running()
