"""
Module for TDX relevant operations.
"""

import hashlib
import json
import logging
import os
import re

from avocado.core import exceptions
from avocado.utils import process
from avocado.utils.network.ports import is_port_available
from virttest import error_context, utils_misc

from provider.hostdev import utils as hostdev_utils

LOG_JOB = logging.getLogger("avocado.test")


class TDXError(Exception):
    """General TDX error"""

    pass


def _expand_cartesian_placeholders(value, params):
    """
    Expand ${key} the same way as cartesian cfg, using final merged params.

    Cartesian substitution only sees keys present when each cfg line is parsed.
    Params added later (profile, --extra-params, job config) stay as literal
    ${key} unless expanded here.
    """
    if "${" not in value:
        return value

    def _repl(match):
        key = match.group(1)
        if params.get(key) is None:
            return match.group(0)
        return str(params[key])

    return re.sub(r"\$\{(.+?)\}", _repl, value)


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


class TDXDcap(object):
    """
    TDX DCAP (Data Center Attestation Primitives) configuration and check.
    """

    def __init__(self, test, params, vm=None):
        """
        :param test: Context of test.
        :param params: params of running ENV.
        :param vm: VM object (optional).
        """
        self._test = test
        self._params = params
        if vm:
            self._vm = vm
            self._monitor = vm.monitor
        else:
            self._vm = None
            self._monitor = None

    def check_preset_service(self, service):
        """
        Check if TDX DCAP preset service is available

        :param service: Service name to check
        """
        if not service:
            return
        # Check if service is enabled
        status = process.system(
            "systemctl is-enabled %s" % service, shell=True, ignore_status=True
        )
        if status != 0:
            self._test.fail(
                "Service %s is not enabled, please check if sgx dcap packages "
                "are installed." % service
            )
        else:
            self._test.log.info("Service %s is enabled", service)

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
        guest_cmd = _expand_cartesian_placeholders(
            self._params["guest_cmd"], self._params
        )
        host_file = os.path.join(deps_dir, host_script)
        guest_script_path = guest_cmd.split(None, 1)[0]
        try:
            self._vm.copy_files_to(host_file, guest_dir)
            session.cmd_output("chmod 755 %s" % guest_script_path)
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
        if not os.path.exists(pccs_config_default_file):
            self._test.cancel(
                "PCCS configuration file %s does not exist" % pccs_config_default_file
            )
        try:
            # Before modifying: cp default.json to pccs.conf
            process.system(
                "cp %s %s" % (pccs_config_default_file, pccs_config_file),
                shell=True,
                timeout=60,
            )
            # Read and modify default.json directly
            with open(pccs_config_default_file, "r") as f:
                config = json.load(f)
            pccs_port = self._params.get("pccs_port")
            if pccs_port:
                config["HTTPS_PORT"] = int(pccs_port)
            # Get ApiKey from environment variable
            api_key = os.environ.get("PCCS_PRIMARY_API_KEY")
            if api_key:
                config["ApiKey"] = api_key
            # Calculate UserTokenHash (SHA512 of user token from config)
            user_token = self._params.get("pccs_user_token", "redhat")
            user_token_hash = hashlib.sha512(user_token.encode()).hexdigest()
            config["UserTokenHash"] = user_token_hash
            # Calculate AdminTokenHash (SHA512 of admin token from config)
            admin_token = self._params.get("pccs_admin_token", "kvmautotest")
            admin_token_hash = hashlib.sha512(admin_token.encode()).hexdigest()
            config["AdminTokenHash"] = admin_token_hash
            openssl_check = process.system(
                "command -v openssl", shell=True, ignore_status=True
            )
            if openssl_check != 0:
                self._test.cancel("Need to install openssl, test cancelled.")
            ssl_dir = self._params.get("pccs_ssl_dir")
            ssl_cert = self._params.get("pccs_ssl_cert")
            ssl_key = self._params.get("pccs_ssl_key")
            generate_ssl_cmd = self._params.get("generate_ssl_cmd")
            if generate_ssl_cmd:
                error_context.context("Generate SSL certificates", self._test.log.info)
                try:
                    process.system(generate_ssl_cmd, shell=True, timeout=60)
                    ca_trust_cert = self._params.get("ca_trust_cert")
                    if ssl_cert and os.path.exists(ssl_cert):
                        process.system(
                            "cp %s %s" % (ssl_cert, ca_trust_cert),
                            shell=True,
                            timeout=60,
                        )
                        process.system("update-ca-trust", shell=True, timeout=60)
                    process.system(
                        "chown -R pccs:pccs %s" % ssl_dir, shell=True, timeout=60
                    )
                    self._test.log.info("Set pccs SSL certificates")
                except Exception as e:
                    raise exceptions.TestFail(
                        "Failed to generate SSL certificates: %s" % str(e)
                    )

            if ssl_cert:
                config["ssl_cert"] = ssl_cert
            if ssl_key:
                config["ssl_key"] = ssl_key

            # Write the updated config to pccs.conf (active config used by PCCS service)
            with open(pccs_config_default_file, "w") as f:
                json.dump(config, f, indent=4)
            self._test.log.info(
                "Successfully updated pccs configuration file: %s",
                pccs_config_default_file,
            )

        except Exception as e:
            raise exceptions.TestFail(
                "Failed to config pccs configuration file: %s" % str(e)
            )

    def setup_sgx_qcnl_config(self):
        """
        Setup SGX QCNL configuration file.
        """
        sgx_qcnl_config_file = self._params.get("sgx_qcnl_config_file")
        pccs_port = self._params.get("pccs_port")
        if not sgx_qcnl_config_file or not pccs_port:
            return

        try:
            if not is_port_available(int(pccs_port), "localhost"):
                raise exceptions.TestFail("Port %s is in use" % pccs_port)
            set_pccs_port = self._params.get("set_pccs_port")
            process.system(set_pccs_port, shell=True, timeout=60)
        except (exceptions.TestFail, exceptions.TestCancel):
            raise

    def restart_dcap_services(self, services):
        """
        Restart DCAP services

        :param services: List of service names to restart
        """
        error_context.context("Restart DCAP services", self._test.log.info)
        for service in services:
            if service:
                try:
                    process.system(
                        "systemctl restart %s" % service, shell=True, timeout=60
                    )
                except Exception as e:
                    self._test.fail(
                        "Failed to restart service %s: %s" % (service, str(e))
                    )

    def verify_dcap_services(self, services, fail_on_inactive=True):
        """
        Verify or check DCAP services are started and enabled.

        :param services: List of service names to verify
        :param fail_on_inactive: If True (default), fail the test when any service
                                 is not active. If False, only check and return
                                 True/False without failing.
        :return: With fail_on_inactive=True (default): returns True when all
                 services are enabled and active; if any is not active, the test
                 is failed via self._test.fail() and the function does not return.
                 With fail_on_inactive=False: returns True when all are active,
                 False when any is not active (caller may continue without exit).
        """
        if fail_on_inactive:
            error_context.context(
                "Verify services are started and enabled", self._test.log.info
            )
        for service in services:
            if service:
                status = process.run(
                    "systemctl is-active %s" % service,
                    shell=True,
                    ignore_status=True,
                )
                if status.exit_status != 0 or status.stdout_text.strip() != "active":
                    if fail_on_inactive:
                        self._test.fail(
                            "Service %s is not active (started), current status: %s"
                            % (service, status.stdout_text.strip())
                        )
                    return False
                if fail_on_inactive:
                    self._test.log.info("Service %s is active", service)
        return True


class TDXPassthroughNet(object):
    """
    Find network device(s) suitable for VFIO pass-through to a TDX guest, and
    verify passed-through devices in the guest via lspci.

    Guarantees:
    - All returned PCI devices are in the same IOMMU group (from one group only).
    - All are "safe" for passthrough: the seed is a PF-backed net iface with
      operstate down; every PCI in the same IOMMU group must have a netdev in
      sysfs and that netdev must be down. (No netdev for a member rejects the
      whole group; any net iface up also rejects the group.)
    """

    SYS_NET_PATH = "/sys/class/net"

    def __init__(self, test):
        """
        :param test: avocado test instance (for cancel when no device found).
        """
        self._test = test

    @staticmethod
    def _net_iface_is_down(iface_path):
        """True if operstate is 'down'."""
        try:
            with open(os.path.join(iface_path, "operstate"), "r") as f:
                return f.read().strip() == "down"
        except IOError:
            return False

    @classmethod
    def _get_net_iface_path_for_pci(cls, pci_address):
        """
        Return ``/sys/class/net/<iface>`` for the PCI BDF, or None.
        Uses ``hostdev_utils.get_ifname_from_pci`` (``.../pci/devices/<BDF>/net/``).
        """
        ifname = hostdev_utils.get_ifname_from_pci(pci_address)
        if not ifname:
            return None
        return os.path.join(cls.SYS_NET_PATH, ifname)

    @classmethod
    def _pci_safe_for_passthrough(cls, pci_address):
        """
        True if this PCI device is safe to pass through: it has a net interface
        in sysfs and operstate is down. Missing netdev returns False (reject
        mixed-function groups where some BDFs are not net-backed in
        /sys/class/net).
        """
        iface_path = cls._get_net_iface_path_for_pci(pci_address)
        if iface_path is None:
            return False  # reject mixed-function groups
        return cls._net_iface_is_down(iface_path)

    @staticmethod
    def _pci_device_info(device_link):
        """
        Return (full_pci, short_pci, driver_name) for the device.
        short_pci strips domain.
        """
        pci_bus_info = os.path.basename(os.path.realpath(device_link))
        short_pci = re.sub(r"^0000:", "", pci_bus_info)
        driver_link = os.path.join(device_link, "driver")
        driver_name = (
            os.path.basename(os.path.realpath(driver_link))
            if os.path.exists(driver_link)
            else "unknown"
        )
        return pci_bus_info, short_pci, driver_name

    @classmethod
    def _passthrough_group_for_down_iface(cls, iface, iface_path):
        """
        If this down PF-backed iface's IOMMU group is all passthrough-safe, return
        ``(pci_list, driver_name)``; otherwise return None.

        :param iface: interface name under /sys/class/net
        :param iface_path: full path to that interface
        :return: ``(pci_list, driver_name)`` or None
        """
        device_link = os.path.join(iface_path, "device")
        iommu_group_path = os.path.join(device_link, "iommu_group", "devices")
        try:
            pci_list = sorted(os.listdir(iommu_group_path))
        except OSError:
            LOG_JOB.warning(
                "Interface %s has no IOMMU group. Check BIOS/Kernel settings.",
                iface,
            )
            return None
        if not pci_list:
            return None
        if not all(cls._pci_safe_for_passthrough(p) for p in pci_list):
            return None
        _pci_bus_info, _short_pci, driver_name = cls._pci_device_info(device_link)
        return pci_list, driver_name

    @classmethod
    def find(cls):
        """
        Find network device(s) suitable for VFIO pass-through to a TDX guest.

        - Iterate network PFs via ``hostdev_utils.get_pci_by_dev_type('pf','network')``
          (sorted BDF order), require ``.../net`` ifname and operstate down.
        - Require the device to have an IOMMU group; collect all PCI devices
          in that group.
        - Require every PCI in the group to have a net iface in sysfs and down.
          (If any member has no netdev or any net iface is up, skip the group.)
        - Return the first group that passes. All returned devices are in the same
          IOMMU group and are safe for passthrough.

        :return: tuple (pci_list, driver) e.g.
                 (['0000:22:00.0', '0000:22:00.1'], 'tg3'), or (None, None) if
                 none. On success pci_list is a non-empty list[str] (all BDFs
                 in one IOMMU group).
        """
        if not os.path.exists(cls.SYS_NET_PATH):
            LOG_JOB.warning("/sys/class/net does not exist")
            return None, None

        for pci in hostdev_utils.get_pci_by_dev_type("pf", "network"):
            ifname = hostdev_utils.get_ifname_from_pci(pci)
            if not ifname:
                continue
            iface_path = os.path.join(cls.SYS_NET_PATH, ifname)
            if not cls._net_iface_is_down(iface_path):
                continue
            found = cls._passthrough_group_for_down_iface(ifname, iface_path)
            if found is None:
                continue
            pci_list, driver_name = found
            LOG_JOB.info(
                "Found passthrough-capable net device(s) in same IOMMU group "
                "(all net down): seed_pci=%s ifname=%s pci_list=%s driver=%s",
                pci,
                ifname,
                pci_list,
                driver_name,
            )
            return pci_list, driver_name

        return None, None

    def find_passthrough_net_device_for_tdx(self):
        """
        Find VFIO-capable net device(s) for TDX passthrough.

        All returned devices are in the same IOMMU group; every member has a
        net iface in sysfs and down. Safe to pass the whole list to one guest
        iommufd.
        If no capable device is found, cancels the test (does not return).

        :return: ``(pci_list, driver)`` where ``pci_list`` is always a non-empty
                 ``list`` of PCI BDF strings, and ``driver`` is the driver name
                 for the seed net device.
        """
        pci_list, driver = self.find()
        if pci_list is None or len(pci_list) == 0:
            self._test.cancel(
                "No VFIO-capable device found (link down, same IOMMU group)"
            )
        return list(pci_list), driver

    def verify_vfio_devices_in_guest_lspci(
        self, session, params, pci_slots, guest_lspci_cmd, visible
    ):
        """
        :param session: guest shell session
        :param params: test params
        :param pci_slots: host PCI BDF list
        :param guest_lspci_cmd: shell command with one ``%s`` for vendor:device
        :param visible: if True expect count ``len(pci_slots)``; if False expect 0
        :return: None
        """
        if not pci_slots:
            self._test.fail("pci_slots is empty for guest lspci verify")
        parent_slot = hostdev_utils.get_parent_slot(pci_slots[0])
        mgr = params.get("hostdev_manager_%s" % parent_slot)
        if mgr is None:
            self._test.fail("Host device manager not found for slot %s" % parent_slot)
        grep = "%s:%s" % (mgr.vendor_id, mgr.device_id)
        expected = len(pci_slots) if visible else 0
        if visible:
            ctx = "Verify %d VFIO device(s) in guest (lspci -nn | grep -c %s)" % (
                len(pci_slots),
                grep,
            )
        else:
            ctx = "Verify VFIO device(s) gone in guest (grep -c %s == 0)" % grep
        error_context.context(ctx, self._test.log.info)
        cmd = guest_lspci_cmd % grep
        st, out, count = 1, "", None

        def verify_pci():
            nonlocal st, out, count
            st, out = session.cmd_status_output(cmd, timeout=60)
            try:
                count = int(out.strip())
            except ValueError:
                count = None
            return count == expected

        if not utils_misc.wait_for(verify_pci, 10, 2, 2):
            self._test.fail(
                "Guest lspci verify failed (visible=%s): expected count %s, "
                "got st=%s count=%s out=%r cmd=%r"
                % (visible, expected, st, count, out.strip(), cmd)
            )
        self._test.log.info(
            "Guest lspci count OK (visible=%s): count=%s", visible, count
        )
