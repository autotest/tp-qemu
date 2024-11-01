import logging
import re

from aexpect import ShellTimeoutError
from virttest import error_context, utils_misc, utils_net
from virttest.utils_test.qemu import windrv_verify_running
from virttest.utils_windows import virtio_win, wmic

LOG_JOB = logging.getLogger("avocado.test")


QUERY_TIMEOUT = 360
INSTALL_TIMEOUT = 360
OPERATION_TIMEOUT = 120


def _chk_cert(session, cert_path):
    chk_cmd = "certutil -verify %s"
    chk_cmd %= cert_path
    # it may take a while to verify cert file so lets wait a little longer
    out = session.cmd(chk_cmd, timeout=QUERY_TIMEOUT)
    if re.search("Expired certificate", out, re.I):
        LOG_JOB.warning("Certificate '%s' is expired!", cert_path)
    if re.search("Incomplete certificate chain", out, re.I):
        LOG_JOB.warning("Incomplete certificate chain! Details:\n%s", out)


def _add_cert(session, cert_path, store):
    add_cmd = "certutil -addstore -f %s %s"
    add_cmd %= (store, cert_path)
    session.cmd(add_cmd, timeout=OPERATION_TIMEOUT)


def _pnpdrv_info(session, name_pattern, props=None):
    cmd = wmic.make_query(
        "path win32_pnpsigneddriver",
        "DeviceName like '%s'" % name_pattern,
        props=props,
        get_swch=wmic.FMT_TYPE_LIST,
    )
    return wmic.parse_list(session.cmd(cmd, timeout=QUERY_TIMEOUT))


def send_key(vm, key):
    # Send key to guest
    for i in key:
        vm.send_key(i)


@error_context.context_aware
def run(test, params, env):
    """
    This Test is mainly used as subtests
    1) Boot up VM
    2) Uninstall driver (Optional)
    3) Reboot or Destroy vm (Based on step 2)
    4) Update / Downgrade / Install driver
    5) Reboot vm
    6) Verify installed driver

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    inst_timeout = int(params.get("driver_install_timeout", INSTALL_TIMEOUT))
    driver_name = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver_name)
    device_name = params["device_name"]
    device_hwid = params["device_hwid"]
    chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
    key_to_install_driver = params.get("key_to_install_driver").split(";")

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    # wait for cdroms having driver installed in case that
    # they are new appeared in this test
    utils_misc.wait_for(
        lambda: utils_misc.get_winutils_vol(session), timeout=OPERATION_TIMEOUT, step=10
    )

    devcon_path = utils_misc.set_winutils_letter(session, params["devcon_path"])
    status, output = session.cmd_status_output(
        "dir %s" % devcon_path, timeout=OPERATION_TIMEOUT
    )
    if status:
        test.error("Not found devcon.exe, details: %s" % output)

    media_type = params["virtio_win_media_type"]
    try:
        get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
        get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
        get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
    except AttributeError:
        test.error("Not supported virtio win media type '%s'", media_type)
    viowin_ltr = get_drive_letter(session)
    if not viowin_ltr:
        test.error("Could not find virtio-win drive in guest")
    guest_name = get_product_dirname(session)
    if not guest_name:
        test.error("Could not get product dirname of the vm")
    guest_arch = get_arch_dirname(session)
    if not guest_arch:
        test.error("Could not get architecture dirname of the vm")

    inf_middle_path = (
        "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
    ).format(name=guest_name, arch=guest_arch)
    inf_find_cmd = 'dir /b /s %s\\%s.inf | findstr "\\%s\\\\"'
    inf_find_cmd %= (viowin_ltr, driver_name, inf_middle_path)
    inf_path = session.cmd(inf_find_cmd, timeout=OPERATION_TIMEOUT).strip()
    test.log.info("Found inf file '%s'", inf_path)

    # `findstr` cannot handle unicode so calling `type` makes it work
    expected_ver = session.cmd(
        "type %s | findstr /i /r DriverVer.*=" % inf_path, timeout=OPERATION_TIMEOUT
    )
    expected_ver = expected_ver.strip().split(",", 1)[-1]
    if not expected_ver:
        test.error("Failed to find driver version from inf file")
    test.log.info("Target version is '%s'", expected_ver)

    if params.get("need_uninstall", "no") == "yes":
        error_context.context("Uninstalling previous installed driver", test.log.info)
        for inf_name in _pnpdrv_info(session, device_name, ["InfName"]):
            pnp_cmd = "pnputil /delete-driver %s /uninstall /force"
            uninst_store_cmd = params.get("uninst_store_cmd", pnp_cmd) % inf_name
            status, output = session.cmd_status_output(uninst_store_cmd, inst_timeout)
            if status not in (0, 3010):
                # for viostor and vioscsi, they need system reboot
                # acceptable status: OK(0), REBOOT(3010)
                test.error(
                    "Failed to uninstall driver '%s' from store, "
                    "details:\n%s" % (driver_name, output)
                )

        uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
        status, output = session.cmd_status_output(uninst_cmd, inst_timeout)
        # acceptable status: OK(0), REBOOT(1)
        if status > 1:
            test.error(
                "Failed to uninstall driver '%s', details:\n"
                "%s" % (driver_name, output)
            )

        if params.get_boolean("need_destroy"):
            vm.destroy()
            vm.create()
            vm = env.get_vm(params["main_vm"])
            # This is a workaround for session logout issue
            session = vm.wait_for_serial_login()
        else:
            session = vm.reboot(session)

    error_context.context("Installing certificates", test.log.info)
    cert_files = utils_misc.set_winutils_letter(session, params.get("cert_files", ""))
    cert_files = [cert.split("=", 1) for cert in cert_files.split()]
    for store, cert in cert_files:
        _chk_cert(session, cert)
        _add_cert(session, cert, store)

    error_context.context("Installing target driver", test.log.info)
    installed_any = False
    for hwid in device_hwid.split():
        output = session.cmd_output("%s find %s" % (devcon_path, hwid))
        if re.search("No matching devices found", output, re.I):
            continue
        # workaround for install driver without signture
        inst_cmd = "%s update %s %s" % (devcon_path, inf_path, hwid)
        key_to_install_driver = params.get("key_to_install_driver").split(";")
        try:
            session.cmd_status_output(inst_cmd, timeout=30)
        except ShellTimeoutError:
            send_key(vm, key_to_install_driver)
        if not utils_misc.wait_for(
            lambda: not session.cmd_status(chk_cmd), 600, 60, 10
        ):
            test.fail("Failed to install driver '%s'" % driver_name)
        if "Red Hat VirtIO Ethernet Adapter" in device_name:
            ext_host = utils_net.get_ip_address_by_interface(
                ifname="%s" % params.get("netdst")
            )
            test.log.info("ext_host of netkvm adapter is %s", ext_host)
            guest_ip = vm.get_address("nic2")
            test.log.info("guest_ip of netkvm adapter is %s", guest_ip)
            status, output = utils_net.ping(
                ext_host, interface=guest_ip, count=10, timeout=60, session=session
            )
            if status:
                test.fail("Ping %s failed, output=%s" % (ext_host, output))

        installed_any |= True
    if not installed_any:
        test.error("Failed to find target devices " "by hwids: '%s'" % device_hwid)

    error_context.context("Verifying target driver", test.log.info)
    session = vm.reboot(session)
    windrv_verify_running(session, test, driver_verifier)

    ver_list = _pnpdrv_info(session, device_name, ["DriverVersion"])
    if expected_ver not in ver_list:
        test.fail(
            "The expected driver version is '%s', but "
            "found '%s'" % (expected_ver, ver_list)
        )
    session.close()
