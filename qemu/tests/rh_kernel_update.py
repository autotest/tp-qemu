import re
import time

from avocado.utils import process
from virttest import data_dir, error_context, storage

QUERY_TIMEOUT = 180
INSTALL_TIMEOUT = 600
DOWNLOAD_TIMEOUT = 1800


@error_context.context_aware
def run(test, params, env):
    """
    Install/upgrade special kernel package via brew tool.

    1) Boot the vm
    2) Get latest kernel package link from brew
    3) Get the version of guest kernel
    4) Compare guest kernel version and brew latest kernel version
    5) Install guest kernel
    6) Installing virtio driver (Optional)
    7) Update initrd file
    8) Make the new installed kernel as default
    9) Update the guest kernel cmdline (Optional)
    10) Reboot guest after updating kernel
    11) Verifying the virtio drivers (Optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def install_rpm(session, url, upgrade=False, nodeps=False, timeout=INSTALL_TIMEOUT):
        cmd = "rpm -ivhf %s" % url
        if upgrade:
            cmd = "rpm -Uvhf %s" % url
        if nodeps:
            cmd += " --nodeps"
        s, o = session.cmd_status_output(cmd, timeout=timeout)
        if s != 0 and ("already" not in o):
            test.fail("Failed to install %s: %s" % (url, o))

    def get_brew_latest_pkg(topdir, tag, pkg, arch=None, list_path=False):
        """
        Get information of the latest package.

        :param topdir: topdir url.
        :param tag: tag of the package.
        :param pkg: package name.
        :param arch: architecture name.
        :param list_path: if shows the path of packages.

        :return: content returned by `latest-pkg`.
        """
        cmd = "brew --topdir='%s' latest-pkg %s %s" % (topdir, tag, pkg)
        cmd += " --quiet"
        if bool(arch):
            cmd += " --arch=%s" % arch
        if list_path:
            cmd += " --paths"
        return process.system_output(cmd, timeout=QUERY_TIMEOUT).decode()

    def get_kernel_info():
        error_context.context("Get latest kernel packages info", test.log.info)
        tag = params["brew_tag"]
        build_name = params.get("kernel_build_name", "kernel")

        o = get_brew_latest_pkg(download_root, tag, build_name)
        try:
            build = re.findall(r"%s[^\s]+" % build_name, o)[0]
        except IndexError:
            test.error("Could not get the latest kernel build name: %s" % o)
        test.log.info("The latest build for tag '%s' is '%s'", tag, build)
        info_cmd = "brew --topdir='%s' buildinfo %s" % (download_root, build)
        buildinfo = process.system_output(info_cmd, timeout=QUERY_TIMEOUT).decode()

        ver_rev = re.sub(build_name, "", build).lstrip("-")
        # customize it since old kernel not has arch name in release name
        build_ver = params.get("kernel_rel_pattern", "{v_r}.{a}")
        build_ver = build_ver.format(v_r=ver_rev, a=params["pkg_arch"])

        pkg_links = []
        for pkg_name in params["kernel_pkgs"].split():
            pkg_params = params.object_params(pkg_name)
            pkg_arch = pkg_params["pkg_arch"]
            # package pattern: n-v-r.a.rpm
            pkg_pattern = "%s-%s.%s.rpm" % (pkg_name, ver_rev, pkg_arch)
            pkg_pattern = re.compile(".*/%s" % re.escape(pkg_pattern))
            match = pkg_pattern.search(buildinfo, re.M | re.I)
            if not match:
                test.error("Could not get the link of '%s' in buildinfo" % pkg_name)
            pkg_path = match.group(0)
            pkg_links.append(pkg_path)

        return build_ver, pkg_links

    def is_virtio_driver_installed():
        s, o = session.cmd_status_output("lsmod | grep virtio")
        if s != 0:
            return False

        for driver in virtio_drivers:
            if driver not in o:
                test.log.debug("%s has not been installed.", driver)
                return False
            test.log.debug("%s has already been installed.", driver)

        return True

    def get_guest_pkgs(session, pkg, qformat=""):
        """
        Query requries packages in guest which name like 'pkg'.

        :parm session: session object to guest.
        :parm pkg: package name without version and arch info.
        :parm qformat: display format(eg, %{NAME}, %{VERSION}).

        :return: list of packages.
        :rtype: list
        """
        cmd = "rpm -q --whatrequires %s" % pkg
        if qformat:
            cmd += " --queryformat='%s\n'" % qformat
        pkgs = session.cmd_output(cmd, timeout=QUERY_TIMEOUT).splitlines()
        pkgs.append(pkg)
        return pkgs

    def upgrade_guest_pkgs(
        session, pkg, arch, debuginfo=False, nodeps=True, timeout=INSTALL_TIMEOUT
    ):
        """
        upgrade given packages in guest os.

        :parm session: session object.
        :parm pkg: package name without version info.
        :parm debuginfo: bool type, if True, install debuginfo package too.
        :parm nodeps: bool type, if True, ignore deps when install rpm.
        :parm timeout: float type, timeout value when install rpm.
        """
        error_context.context("Upgrade package '%s' in guest" % pkg, test.log.info)
        pkgs = get_guest_pkgs(session, pkg, "%{NAME}")

        tag = params.get("brew_tag")
        pkg_urls = get_brew_latest_pkg(
            download_root, tag, pkg, arch, list_path=True
        ).splitlines()
        for url in pkg_urls:
            if "debuginfo" in url and not debuginfo:
                continue
            upgrade = bool(list(filter(lambda x: x in url, pkgs)))
            test.log.info("Install packages from: %s", url)
            install_rpm(session, url, upgrade, nodeps, timeout)

    def get_guest_kernel_version(session):
        return session.cmd("uname -r").strip()

    def compare_version(current, expected):
        if current == expected:
            return 0
        cur_ver = re.split("[.+-]", current)
        cur_ver = [int(item) for item in cur_ver if item.isdigit()]
        cur_len = len(cur_ver)
        exp_ver = re.split("[.+-]", expected)
        exp_ver = [int(item) for item in exp_ver if item.isdigit()]
        exp_len = len(exp_ver)
        if cur_len != exp_len:
            # we assume that the version which contains more fields
            # always be the newer one
            return (cur_len > exp_len) - (cur_len < exp_len)
        for c_ver, e_ver in zip(cur_ver, exp_ver):
            if c_ver > e_ver:
                return 1
            elif c_ver < e_ver:
                return -1

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    download_root = params["download_root_url"]

    inst_timeout = int(params.get("install_pkg_timeout", INSTALL_TIMEOUT))
    kernel_deps_pkgs = params.get("kernel_deps_pkgs", "").split()
    install_virtio = params.get("install_virtio", "no") == "yes"
    verify_virtio = params.get("verify_virtio", "no") == "yes"
    virtio_drivers = params.get("virtio_drivers_list", "").split()
    args_removed = params.get("args_removed", "").split()
    args_added = params.get("args_added", "").split()

    kernel_ver, kernel_pkgs = get_kernel_info()
    test.log.info("Kernel version   :  %s", kernel_ver)
    test.log.info("Kernel package(s):")
    for pkg in kernel_pkgs:
        test.log.info("    %s", pkg)

    updated = True
    session = vm.wait_for_login()
    cur_ver = get_guest_kernel_version(session)
    test.log.info("Guest current kernel version is '%s'", cur_ver)
    if compare_version(cur_ver, kernel_ver) >= 0:
        test.log.info("Guest current kernel matches the requirement")
        if is_virtio_driver_installed():
            install_virtio = False
        kernel_ver = cur_ver
        updated = False
    else:
        test.log.info(
            "Guest current kernel does not match the " "requirement, processing upgrade"
        )
        for pkg in kernel_deps_pkgs:
            pkg_params = params.object_params(pkg)
            arch = pkg_params["pkg_arch"]
            upgrade_guest_pkgs(session, pkg, arch)

        error_context.context("Install guest kernel package(s)", test.log.info)
        # not install kernel pkgs via rpm since need to install them atomically
        kernel_pkg_dir = "/tmp/kernel_packages"
        session.cmd("mkdir -p %s" % kernel_pkg_dir)
        # old guest not support installing via url directly
        download_cmd = "curl -kL %s -o %s/%s"
        for pkg_url in kernel_pkgs:
            pkg_name = pkg_url.rsplit("/", 1)[-1]
            status, output = session.cmd_status_output(
                download_cmd % (pkg_url, kernel_pkg_dir, pkg_name),
                timeout=DOWNLOAD_TIMEOUT,
            )
            if status:
                test.fail("Failed to download %s: %s" % (pkg_url, output))
        pm_bin = "dnf"
        if session.cmd_status("command -v %s" % pm_bin) != 0:
            pm_bin = "yum"
        inst_cmd = "%s localinstall %s/* -y --nogpgcheck" % (pm_bin, kernel_pkg_dir)
        status, output = session.cmd_status_output(inst_cmd, timeout=inst_timeout)
        if status != 0:
            test.fail("Failed to install kernel package(s): %s" % output)
        session.cmd("rm -rf %s" % kernel_pkg_dir)

    kernel_path = "/boot/vmlinuz-%s" % kernel_ver
    if install_virtio:
        error_context.context("Installing virtio driver", test.log.info)
        initrd_prob_cmd = "grubby --info=%s" % kernel_path
        s, o = session.cmd_status_output(initrd_prob_cmd)
        if s != 0:
            test.error("Could not get guest kernel information: %s" % o)
        try:
            initrd_path = re.findall("initrd=(.*)", o)[0]
        except IndexError:
            test.error("Could not get initrd path from guest: %s" % o)

        error_context.context("Update initrd file", test.log.info)
        driver_list = ["--with=%s" % drv for drv in virtio_drivers]
        mkinitrd_cmd = "mkinitrd -f %s " % initrd_path
        mkinitrd_cmd += " ".join(driver_list)
        mkinitrd_cmd += " %s" % kernel_ver
        s, o = session.cmd_status_output(mkinitrd_cmd, timeout=360)
        if s != 0:
            test.fail("Failed to install virtio driver: %s" % o)

    # make sure the newly installed kernel as default
    if updated:
        error_context.context("Make the new installed kernel as default", test.log.info)
        make_def_cmd = "grubby --set-default=%s " % kernel_path
        s, o = session.cmd_status_output(make_def_cmd)
        if s != 0:
            test.error("Fail to set default kernel: %s" % o)

    # remove or add the required arguments
    update_kernel_cmd = ""
    if args_removed:
        update_kernel_cmd += ' --remove-args="%s"' % " ".join(args_removed)
    if args_added:
        update_kernel_cmd += ' --args="%s"' % " ".join(args_added)
    if update_kernel_cmd:
        update_kernel_cmd = "grubby --update-kernel=%s %s" % (
            kernel_path,
            update_kernel_cmd,
        )
    update_kernel_cmd = params.get("update_kernel_cmd", update_kernel_cmd)
    if update_kernel_cmd:
        error_context.context("Update the guest kernel cmdline", test.log.info)
        s, o = session.cmd_status_output(update_kernel_cmd)
        if s != 0:
            test.error("Fail to modify kernel cmdline: %s" % o)

    # upgrade listed packages to latest version.
    for pkg in params.get("upgrade_pkgs", "").split():
        pkg_info = params.object_params(pkg)
        arch = pkg_info["pkg_arch"]
        nodeps = pkg_info.get("ignore_deps") == "yes"
        install_debuginfo = pkg_info.get("install_debuginfo") == "yes"
        ver_before = session.cmd_output("rpm -q %s" % pkg)
        upgrade_guest_pkgs(session, pkg, arch, install_debuginfo, nodeps, inst_timeout)
        ver_after = session.cmd_output("rpm -q %s" % pkg)
        if "not installed" in ver_before:
            mesg = "Install '%s' in guest" % ver_after
        else:
            mesg = "Upgrade '%s' from '%s'  to '%s'" % (pkg, ver_before, ver_after)
        test.log.info(mesg)

    # reboot guest and do verify
    error_context.context("Reboot guest after updating kernel", test.log.info)
    time.sleep(int(params.get("sleep_before_reset", 10)))
    session = vm.reboot(session)
    cur_ver = get_guest_kernel_version(session)
    if compare_version(cur_ver, kernel_ver) != 0:
        test.fail(
            "Failed to verify the guest kernel, expected version '%s' "
            "vs current version '%s'" % (kernel_ver, cur_ver)
        )
    if verify_virtio:
        error_context.context("Verifying the virtio drivers", test.log.info)
        if not is_virtio_driver_installed():
            test.fail("Fail to verify the installation of virtio drivers")

    # update image
    error_context.context("OS updated, commit changes to disk", test.log.info)
    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    image_filename = storage.get_image_filename(params, base_dir)
    block = vm.get_block({"backing_file": image_filename})
    vm.monitor.cmd("stop")
    vm.monitor.send_args_cmd("commit %s" % block)
