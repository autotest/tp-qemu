import os
import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_package
from virttest.qemu_devices import qdevices
from virttest.utils_params import Params

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test usb redirection

    1) Check host configurations
    2) Start usbredirserver on host (optional)
    3) Preprocess VM
    4) Start USB redirection via spice (optional)
    5) Check the boot menu list (optional)
    6) Check the redirected USB device in guest

    :param test: QEMU test object
    :param params: Dictionary with test parameters
    :param env: Dictionary with test environment.
    """

    def _start_usbredir_server(port):
        process.getoutput("killall usbredirserver")
        usbredir_server = utils_misc.get_binary("usbredirserver", params)
        usbredirserver_args = usbredir_server + " -p %s " % port
        usbredirserver_args += " %s:%s" % (vendorid, productid)
        usbredirserver_args += " > /dev/null 2>&1"
        rv_thread = utils_misc.InterruptedThread(os.system, (usbredirserver_args,))
        rv_thread.start()

    def create_repo():
        test.log.info("Create temp repository")
        version_cmd = 'grep "^VERSION_ID=" /etc/os-release | cut -d = -f2'
        version_id = process.getoutput(version_cmd).strip('"')
        major, minor = version_id.split(".")
        baseurl = params["temprepo_url"]
        baseurl = baseurl.replace("MAJOR", major)
        content = "[temp]\nname=temp\nbaseurl=%s\nenable=1\n" % baseurl
        content += "gpgcheck=0\nskip_if_unavailable=1"
        create_cmd = r'echo -e "%s" > /etc/yum.repos.d/temp.repo' % content
        process.system(create_cmd, shell=True)

    def _host_config_check():
        status = True
        err_msg = ""
        if option == "with_negative_config":
            out = process.getoutput("dmesg")
            pattern = r"usb (\d-\d+(?:.\d)?):.*idVendor=%s, idProduct=%s"
            pattern = pattern % (vendorid, productid)
            obj = re.search(pattern, out, re.ASCII)
            if not obj:
                status = False
                err_msg = "Fail to get the USB device info in host dmesg"
                return (status, err_msg)
            error_context.context("Make USB device unconfigured", test.log.info)
            unconfig_value = params["usbredir_unconfigured_value"]
            cmd = "echo %s > /sys/bus/usb/devices/%s/bConfigurationValue"
            cmd = cmd % (unconfig_value, obj.group(1))
            test.log.info(cmd)
            s, o = process.getstatusoutput(cmd)
            if s:
                status = False
                err_msg = "Fail to unconfig the USB device, output: %s" % o
                return (status, err_msg)

        if backend == "spicevmc":
            gui_group = "Server with GUI"
            out = process.getoutput("yum group list --installed", shell=True)
            obj = re.search(r"(Installed Environment Groups:.*?)^\S", out, re.S | re.M)
            if not obj or gui_group not in obj.group(1):
                gui_groupinstall_cmd = "yum groupinstall -y '%s'" % gui_group
                s, o = process.getstatusoutput(gui_groupinstall_cmd, shell=True)
                if s:
                    status = False
                    err_msg = "Fail to install '%s' on host, " % gui_group
                    err_msg += "output: %s" % o
                    return (status, err_msg)
            virt_viewer_cmd = "rpm -q virt-viewer || yum install -y virt-viewer"
            s, o = process.getstatusoutput(virt_viewer_cmd, shell=True)
            if s:
                status = False
                err_msg = "Fail to install 'virt-viewer' on host, "
                err_msg += "output: %s" % o
                return (status, err_msg)
        elif backend == "tcp_socket":
            create_repo()
            if not utils_package.package_install("usbredir-server"):
                status = False
                err_msg = "Fail to install 'usbredir-server' on host"
                return (status, err_msg)
        return (status, err_msg)

    def _usbredir_preprocess():
        def _generate_usb_redir_cmdline():
            extra_params = ""
            _backend = "socket" if "socket" in backend else backend
            chardev_id = usbredir_params.get(
                "chardev_id", "chardev_%s" % usbredirdev_name
            )
            chardev_params = Params({"backend": _backend, "id": chardev_id})
            if backend == "spicevmc":
                chardev_params["debug"] = usbredir_params.get("chardev_debug")
                chardev_params["name"] = usbredir_params.get("chardev_name")
            else:
                chardev_params["host"] = usbredir_params["chardev_host"]
                chardev_params["port"] = free_port  # pylint: disable=E0606
                chardev_params["server"] = usbredir_params.get("chardev_server")
                chardev_params["wait"] = usbredir_params.get("chardev_wait")
            chardev = qdevices.CharDevice(chardev_params, chardev_id)
            usbredir_dev = qdevices.QDevice("usb-redir", aobject=usbredirdev_name)
            usbredir_filter = usbredir_params.get("usbdev_option_filter")
            usbredir_bootindex = usbredir_params.get("usbdev_option_bootindex")
            usbredir_bus = usbredir_params.get("usbdev_bus")
            usbredir_dev.set_param("id", "usb-%s" % usbredirdev_name)
            usbredir_dev.set_param("chardev", chardev_id)
            usbredir_dev.set_param("filter", usbredir_filter)
            usbredir_dev.set_param("bootindex", usbredir_bootindex)
            usbredir_dev.set_param("bus", usbredir_bus)
            extra_params += " ".join([chardev.cmdline(), usbredir_dev.cmdline()])
            return extra_params

        extra_params = _generate_usb_redir_cmdline()
        params["extra_params"] = extra_params
        if backend == "spicevmc":
            params["paused_after_start_vm"] = "yes"
            del params["spice_password"]
            del params["spice_addr"]
            del params["spice_image_compression"]
            del params["spice_zlib_glz_wan_compression"]
            del params["spice_streaming_video"]
            del params["spice_agent_mouse"]
            del params["spice_playback_compression"]
            del params["spice_ipv4"]
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    def _start_spice_redirection():
        def _rv_connection_check():
            rv_pid = process.getoutput("pidof %s" % rv_binary)
            spice_port = vm.get_spice_var("spice_port")
            cmd = 'netstat -ptn | grep "^tcp.*127.0.0.1:%s.*ESTABLISHED %s.*"'
            cmd = cmd % (spice_port, rv_pid)
            s, o = process.getstatusoutput(cmd)
            if s:
                return False
            test.log.info("netstat output:\n%s", o)
            return True

        status = True
        err_msg = ""
        rv_binary_path = utils_misc.get_binary(rv_binary, params)
        spice_port = vm.get_spice_var("spice_port")
        rv_args = rv_binary_path + " spice://localhost:%s " % spice_port
        rv_args += "--spice-usbredir-redirect-on-connect="
        rv_args += "'-1,0x%s,0x%s,-1,1'" % (vendorid, productid)
        rv_args += " > /dev/null 2>&1"
        rv_thread = utils_misc.InterruptedThread(os.system, (rv_args,))
        rv_thread.start()
        if not utils_misc.wait_for(_rv_connection_check, timeout, 60):
            status = False
            err_msg = "Fail to establish %s connection" % rv_binary
        return (status, err_msg)

    def boot_check(info):
        """
        boot info check
        """
        return re.search(info, vm.serial_console.get_stripped_output())

    def _usb_dev_verify():
        error_context.context("Check USB device in guest", test.log.info)
        if session.cmd_status(lsusb_cmd):
            return False
        return True

    def _kill_rv_proc():
        s, o = process.getstatusoutput("pidof %s" % rv_binary)
        if not s:
            process.getoutput("killall %s" % rv_binary)

    def _get_usb_mount_point():
        """Get redirected USB stick mount point"""
        dmesg_cmd = "dmesg | grep 'Attached SCSI removable disk'"
        s, o = session.cmd_status_output(dmesg_cmd)
        if s:
            test.error("Fail to get redirected USB stick in guest.")
        dev = re.findall(r"\[(sd\w+)\]", o)[0]
        mounts_cmd = "cat /proc/mounts | grep /dev/%s" % dev
        s, o = session.cmd_status_output(mounts_cmd)
        if s:
            s, o = session.cmd_status_output("mount /dev/%s /mnt" % dev)
            if s:
                test.error("Fail to mount /dev/%s, output: %s" % (dev, o))
            mp = "/mnt"
        else:
            mp = re.findall(r"/dev/%s\d*\s+(\S+)\s+" % dev, o)[0]
        return mp

    def _usb_stick_io(mount_point):
        """
        Do I/O operations on passthrough USB stick
        """
        error_context.context("Read and write on USB stick ", test.log.info)
        testfile = os.path.join(mount_point, "testfile")
        iozone_cmd = params.get("iozone_cmd", " -a -I -r 64k -s 1m -i 0 -i 1 -f %s")
        iozone_test.run(iozone_cmd % testfile)  # pylint: disable=E0606

    usbredirdev_name = params["usbredirdev_name"]
    usbredir_params = params.object_params(usbredirdev_name)
    backend = usbredir_params.get("chardev_backend", "spicevmc")
    if backend not in ("spicevmc", "tcp_socket"):
        test.error("Unsupported char device backend type: %s" % backend)

    if backend == "spicevmc" and params.get("display") != "spice":
        test.cancel("Only support spice connection")

    option = params.get("option")
    vendorid = params["usbredir_vendorid"]
    productid = params["usbredir_productid"]
    timeout = params.get("wait_timeout", 600)
    lsusb_cmd = "lsusb -v -d %s:%s" % (vendorid, productid)
    usb_stick = "Mass Storage" in process.getoutput(lsusb_cmd)
    rv_binary = params.get("rv_binary", "remote-viewer")

    error_context.context("Check host configurations", test.log.info)
    s, o = _host_config_check()
    if not s:
        test.error(o)

    if backend == "tcp_socket":
        free_port = utils_misc.find_free_port()
        _start_usbredir_server(free_port)

    error_context.context("Preprocess VM", test.log.info)
    _usbredir_preprocess()
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    if backend == "spicevmc":
        error_context.context("Start USB redirection via spice", test.log.info)
        s, o = _start_spice_redirection()
        if not s:
            test.error(o)
        vm.resume()

    if option == "with_bootindex":
        error_context.context("Check 'bootindex' option", test.log.info)
        boot_menu_hint = params["boot_menu_hint"]
        boot_menu_key = params["boot_menu_key"]
        if not utils_misc.wait_for(lambda: boot_check(boot_menu_hint), timeout, 1):
            test.fail("Could not get boot menu message")

        # Send boot menu key in monitor.
        vm.send_key(boot_menu_key)

        output = vm.serial_console.get_stripped_output()
        boot_list = re.findall(r"^\d+\. (.*)\s", output, re.M)
        if not boot_list:
            test.fail("Could not get boot entries list")
        test.log.info("Got boot menu entries: '%s'", boot_list)

        bootindex = int(params["usbdev_option_bootindex_%s" % usbredirdev_name])
        if "USB" not in boot_list[bootindex]:
            test.fail("'bootindex' option of usb-redir doesn't take effect")

        if usb_stick:
            error_context.context("Boot from redirected USB stick", test.log.info)
            boot_entry_info = params["boot_entry_info"]
            vm.send_key(str(bootindex + 1))
            if not utils_misc.wait_for(lambda: boot_check(boot_entry_info), timeout, 1):
                test.fail("Could not boot from redirected USB stick")
        return

    error_context.context("Login to guest", test.log.info)
    session = vm.wait_for_login()

    if params.get("policy") == "deny":
        if _usb_dev_verify():
            error_msg = "Redirected USB device can be found in guest"
            error_msg += " while policy is deny"
            test.fail(error_msg)
        if backend == "spicevmc":
            _kill_rv_proc()
        return

    if not _usb_dev_verify():
        if backend == "tcp_socket":
            process.system("killall usbredirserver", ignore_status=True)
        test.fail("Can not find the redirected USB device in guest")

    if usb_stick:
        iozone_test = None
        try:
            mount_point = _get_usb_mount_point()
            iozone_test = generate_instance(params, vm, "iozone")
            _usb_stick_io(mount_point)
        finally:
            if iozone_test:
                iozone_test.clean()

    if backend == "tcp_socket":
        process.system("killall usbredirserver", ignore_status=True)

    session.close()
