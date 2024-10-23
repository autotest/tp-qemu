from distutils.version import LooseVersion

from avocado.utils import distro, process
from virttest import error_context

QUERY_TIMEOUT = 360
INSTALL_TIMEOUT = 360
OPERATION_TIMEOUT = 1200


@error_context.context_aware
def run(test, params, env):
    """
    Test update of qemu-kvm
    1) Boot the VM
    2) Install qemu-kvm metapackage from compose
    3) Clone component_management tool
    4) Verify host and guest qemu versions
    5) Update qemu-kvm using chosen package manager
    6) Verify installed qemu-kvm version

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    qemu_package = params["qemu_package_install"]
    pm_tool = params["pm_tool"]

    def install_qemu(session):
        """
        Install compose version of qemu-kvm pkg by the name provided in cfg
        """
        cmd = "{} install -y {}".format(pm_tool, qemu_package)
        s, o = session.cmd_status_output(cmd, timeout=OPERATION_TIMEOUT)
        if s != 0:
            test.error("Installation of '{}' failed with: {}".format(qemu_package, o))
        test.log.info("Installation of '%s' succeeded", qemu_package)

    def install_component_management(session):
        """
        Clone component management repository for preparation of necessary
        repositories containing qemu-kvm build or whole virt module
        """
        cmd_clone = "git clone --depth=1 {} -b {} {}".format(
            params["cm_repo"], params["cm_branch"], params["cm_path"]
        )
        s_clone, o_clone = session.cmd_status_output(
            cmd_clone, timeout=OPERATION_TIMEOUT
        )
        if s_clone != 0:
            test.error(
                "Clonning of '{}' failed with: {}".format(params["cm_repo"], o_clone)
            )
        test.log.info("Clonning of '%s' succeeded", params["cm_repo"])

    def _get_installed_qemu_info(session=None):
        """
        Get info about qemu versions used on guest or host, function returns
        dict containing NVR, TARGET and module_id (in case of module only)
        """
        cmd = f"rpm -q {qemu_package}"
        if session is not None:
            out = session.cmd(cmd, timeout=QUERY_TIMEOUT)
            tgt = (
                process.run(
                    "cat /etc/os-release | grep VERSION_ID | cut -d'=' -f2", shell=True
                )
                .stdout_text.strip()
                .replace('"', "")
            )
        else:
            out = process.run(cmd, shell=True).stdout_text.strip()
            distro_details = distro.detect()
            tgt = f"{distro_details.version}.{distro_details.release}"
        # Drop arch information from NVR e.g. '.x86_64'
        nvr = out.rsplit(".", 1)[0]
        return {
            "nvr": nvr,
            "target": tgt,
        }

    def verify_qemu_version(host_qemu, guest_qemu):
        """
        Verify if available qemu-kvm pkg (no matter module or build) is newer
        than installed one, if so return its NVR accordingly
        """
        # Check if target is the same for guest and host
        if host_qemu["target"] != guest_qemu["target"]:
            test.cancel(
                "Guest target target '{}' differs from host '{}'".format(
                    guest_qemu["target"], host_qemu["target"]
                )
            )
        # Check if qemu-versions in the available and guest one differs
        if LooseVersion(host_qemu["nvr"]) > LooseVersion(guest_qemu["nvr"]):
            test.log.info(
                "Available qemu-kvm '%s' is newer compared to guest's '%s'",
                host_qemu["nvr"],
                guest_qemu["nvr"],
            )
        else:
            test.cancel(
                "Available qemu-kvm '{}' is older or same compared to guest's "
                "'{}'".format(host_qemu["nvr"], guest_qemu["nvr"])
            )
        return host_qemu["nvr"]

    def update_guest_qemu(session, install_id):
        """
        Prepare repository containing the newest version of qemu-kvm package,
        handle modules if needed and run upgrade to the newest version
        """
        # Prepare module or build repo containing newer version of qemu-kvm
        cmd = f"python3 {params['cm_path']}{params['cm_cmd']} {install_id}"
        test.log.info("Running: %s", cmd)
        try:
            session.cmd(cmd, timeout=OPERATION_TIMEOUT)
            test.log.info("Creation of repo '%s' succeeded", install_id)
        except Exception as e:
            test.error("Creation of repo '{}' failed with: {}".format(install_id, e))
        # Disable and enable new module if module is used
        if "+" in install_id:
            # Get virt module stream ('rhel' or 'av') on the host
            stream = process.run(
                f"{pm_tool} module list --enabled | grep virt"
                + "| awk -F ' ' '{{print $2}}' | head -1",
                shell=True,
            ).stdout_text.strip()
            disable_cmd = f"{pm_tool} module disable -y virt"
            s_disable, o_disable = session.cmd_status_output(
                disable_cmd, timeout=QUERY_TIMEOUT
            )
            if s_disable != 0:
                test.fail("Disable of module virt failed with: {}".format(o_disable))
            else:
                test.log.info("Disable of module virt succeeded")
            enable_cmd = f"{pm_tool} module enable -y virt:{stream}"
            s_enable, o_enable = session.cmd_status_output(
                enable_cmd, timeout=QUERY_TIMEOUT
            )
            if s_enable != 0:
                test.fail(
                    "Enable of module virt:{} failed with: {}".format(stream, o_enable)
                )
            else:
                test.log.info("Enable of module virt:%s succeeded", stream)
        # Run upgrade to newer qemu-kvm version
        if "+" in install_id:
            cmd_upgrade = f"{pm_tool} module update -y virt:{stream}"
        else:
            cmd_upgrade = "{} upgrade -y {}".format(pm_tool, qemu_package)
        s_upgrade, o_upgrade = session.cmd_status_output(
            cmd_upgrade, timeout=INSTALL_TIMEOUT
        )
        if s_upgrade != 0:
            test.fail("Upgrade of '{}' failed with: {}".format(qemu_package, o_upgrade))
        test.log.info("Upgrade of '%s' succeeded", qemu_package)

    def verify_installed_qemu(host_qemu, guest_qemu):
        """
        Verify installated version of qemu-kvm matches expected one by its NVR
        """
        expected_nvr = host_qemu["nvr"]
        installed_nvr = guest_qemu["nvr"]
        if installed_nvr == expected_nvr:
            test.log.info("NVR of installed pkg '%s' is correct", installed_nvr)
        else:
            test.fail(
                "NVR of installed pkg '{}' differs from expected '{}'".format(
                    installed_nvr, expected_nvr
                )
            )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    install_qemu(session)
    install_component_management(session)
    host_qemu = _get_installed_qemu_info()
    guest_qemu_before = _get_installed_qemu_info(session)
    install_id = verify_qemu_version(host_qemu, guest_qemu_before)
    update_guest_qemu(session, install_id)
    guest_qemu_after = _get_installed_qemu_info(session)
    verify_installed_qemu(host_qemu, guest_qemu_after)
    session.close()
