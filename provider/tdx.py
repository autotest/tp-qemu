"""
Module for TDX relevant operations.
"""

import os
import logging
import json
import hashlib
import socket
import re

from avocado.utils import process
from virttest import error_context

LOG_JOB = logging.getLogger("avocado.test")


class TDXError(Exception):
    """General TDX error"""

    pass


class TDXHostCapability(object):
    """
    Hypervisor TDX capabilities check.
    """

    def __init__(self, test, params):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        """
        self._test = test
        self._params = params

    def validate_tdx_cap(self):
        """
        Validate if host enable TDX
        """
        tdx_module_path = self._params["tdx_module_path"]
        if os.path.exists(tdx_module_path):
            with open(tdx_module_path) as f:
                output = f.read().strip()
            if output not in self._params.objects("module_status"):
                self._test.cancel("Host tdx support check fail.")
        else:
            self._test.cancel("Host tdx support check fail.")

    def validate_tdx_config(self):
        """
        Validate if host TDX configuration satisfy test requirement
        """
        pass


class TDXChecker(object):
    """
    Basic verification on TDX capabilities for both host and guest.
    """

    def __init__(self, test, params, vm):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        :param vm: VM object.
        """
        self._test = test
        self._params = params
        self._vm = vm
        self._monitor = vm.monitor

    def verify_tdx_flags(self, qmp_command, flags):
        """
        Check if TDX cpu flags enabled in qmp cmd

        :param qmp_command: query TDX qmp command output
        :param flags: TDX flags need to be verified
        """
        pass

    def verify_qmp_host_tdx_cap(self):
        """
        Verify query host TDX capabilities qmp cmd
        """
        pass

    def verify_qmp_guest_tdx_cap(self):
        """
        Verify query guest TDX capabilities qmp cmd
        """
        pass

    def verify_guest_tdx_status(self, cmd_output):
        """
        Verify guest TDX status by cmd output

        :param cmd_output: get TDX info cmd output.
        """
        pass


class TDXDcap(object):
    """
    TDX DCAP (Data Center Attestation Primitives) configuration and check.
    """

    def __init__(self, test, params, vm=None):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        :param vm: VM object (optional, only needed for guest-related operations).
        """
        self._test = test
        self._params = params
        if vm:
            self._vm = vm
            self._monitor = vm.monitor
        else:
            self._vm = None
            self._monitor = None

    def validate_dcap_config(self):
        """
        Validate if TDX DCAP configuration is correct
        """
        pass

    def check_preset_service(self, service):
        """
        Check if TDX DCAP preset service is available

        :param service: Service name to check
        """
        if not service:
            return
        # Check if service is enabled
        status = process.run("systemctl is-enabled %s" % service, shell=True, ignore_status=True)
        if status.exit_status != 0:
            self._test.fail("Service %s is not enabled，please check if sgx dcap packages are installed." % service)
        else:
            self._test.log.info("Service %s is enabled" % service)

    def verify_dcap_attestation(self, session, deps_dir):
        """
        Verify TDX DCAP attestation functionality

        :param session: VM session object
        :param deps_dir: Dependencies directory path
        """
        if not self._vm:
            raise TDXError("VM object is required for attestation verification")
        error_context.context("Start to do attestation", self._test.log.info)
        if not self._params.get("guest_script"):
            self._test.cancel("Missing guest_script for attestation.")
        guest_dir = self._params["guest_dir"]
        host_script = self._params["host_script"]
        guest_cmd = self._params["guest_cmd"]
        host_file = os.path.join(deps_dir, host_script)
        try:
            self._vm.copy_files_to(host_file, guest_dir)
            session.cmd_output("chmod 755 %s" % guest_cmd)
        except Exception as e:
            self._test.fail("Guest test preparation fail: %s" % str(e))
        s = session.cmd_status(guest_cmd, timeout=360)
        if s:
            self._test.fail("Guest script error")

    def setup_pccs_config(self):
        """
        Setup PCCS configuration file.
        """
        error_context.context("Config pccs configuration file", self._test.log.info)
        pccs_config_dir = self._params.get("pccs_config_dir")
        pccs_config_file = os.path.join(pccs_config_dir, "pccs.conf")
        pccs_config_default_file = os.path.join(pccs_config_dir, "default.json")
        if not pccs_config_default_file:
            return
        
        try:
            process.run("cp %s %s" % (pccs_config_default_file, pccs_config_file), shell=True, timeout=60)
            # Read the original config file
            with open(pccs_config_file, 'r') as f:
                config = json.load(f)
            
            # Get ApiKey from environment variable
            api_key = os.environ["PCCS_PRIMARY_API_KEY"]
            if api_key:
                config["ApiKey"] = api_key
            
            # Calculate UserTokenHash (SHA512 of user token from config)
            user_token = self._params.get("pccs_user_token")
            user_token_hash = hashlib.sha512(user_token.encode()).hexdigest()
            config["UserTokenHash"] = user_token_hash
            
            # Calculate AdminTokenHash (SHA512 of admin token from config)
            admin_token = self._params.get("pccs_admin_token")
            admin_token_hash = hashlib.sha512(admin_token.encode()).hexdigest()
            config["AdminTokenHash"] = admin_token_hash
            
            # Update ssl_cert and ssl_key 
            openssl_check = process.run("command -v openssl", shell=True, ignore_status=True)
            if openssl_check.exit_status != 0:
                self._test.cancel("Need to install openssl, test cancelled.")
            
            ssl_dir = self._params.get("pccs_ssl_dir")
            ssl_cert = self._params.get("pccs_ssl_cert")
            ssl_key = self._params.get("pccs_ssl_key")
            generate_ssl_cmd = self._params.get("generate_ssl_cmd")
            if generate_ssl_cmd:
                error_context.context("Generate SSL certificates", self._test.log.info)
                try:
                    process.run(generate_ssl_cmd, shell=True, timeout=60)
                    ca_trust_cert = self._params.get("ca_trust_cert")
                    if ssl_cert and os.path.exists(ssl_cert):
                        process.run("cp %s %s" % (ssl_cert, ca_trust_cert), shell=True, timeout=60)
                        process.run("update-ca-trust", shell=True, timeout=60)
                    
                    process.run("chown -R pccs:pccs %s" % ssl_dir, shell=True, timeout=60)
                    self._test.log.info("Set pccs SSL certificates")
                except Exception as e:
                    self._test.fail("Failed to generate SSL certificates: %s" % str(e))

            if ssl_cert:
                config["ssl_cert"] = ssl_cert
            if ssl_key:
                config["ssl_key"] = ssl_key
            
            # Write the updated config back to file
            with open(pccs_config_file, 'w') as f:
                json.dump(config, f, indent=4)
            
            self._test.log.info("Successfully updated pccs configuration file: %s" % pccs_config_default_file)
        except Exception as e:
            self._test.fail("Failed to config pccs configuration file: %s" % str(e))

    def setup_sgx_qcnl_config(self):
        """
        Setup SGX QCNL configuration file.
        """
        sgx_qcnl_config_file = self._params.get("sgx_qcnl_config_file")
        pccs_port = self._params.get("pccs_port")
        if not sgx_qcnl_config_file:
            return
        
        try:
            # Check if port is available
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex(('localhost', int(pccs_port))) == 0:
                sock.close()
                self._test.fail("Port %s is already in use" % pccs_port)
            sock.close()
            
            # Read and update config
            with open(sgx_qcnl_config_file, 'r') as f:
                sgx_config = json.load(f)
            
            if "pccs_url" in sgx_config:
                sgx_config["pccs_url"] = re.sub(r':8081/', ':%s/' % pccs_port, sgx_config["pccs_url"])
            
            with open(sgx_qcnl_config_file, 'w') as f:
                json.dump(sgx_config, f, indent=4)
        except Exception as e:
            self._test.fail("Failed to update SGX QCNL configuration file: %s" % str(e))

    def restart_dcap_services(self, services):
        """
        Restart DCAP services

        :param services: List of service names to restart
        """
        error_context.context("Restart DCAP services", self._test.log.info)
        for service in services:
            if service:
                try:
                    result = process.run("systemctl restart %s" % service, shell=True, timeout=60)
                except Exception as e:
                    self._test.fail("Failed to restart service %s: %s" % (service, str(e)))

    def verify_dcap_services(self, services):
        """
        Verify DCAP services are started and enabled

        :param services: List of service names to verify
        """
        error_context.context("Verify services are started and enabled", self._test.log.info)
        for service in services:
            if service:
                # Check if service is active (started)
                status = process.run("systemctl is-active %s" % service, shell=True, ignore_status=True)
                if status.exit_status != 0 or status.stdout_text.strip() != "active":
                    self._test.fail("Service %s is not active (started), current status: %s" % (service, status.stdout_text.strip()))
                else:
                    self._test.log.info("Service %s is active" % service)

