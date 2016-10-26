import os
import re
import time
import logging

from autotest.client.shared import error
from autotest.client.shared import utils

from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    Install/upgrade special kernel package via brew tool or link. And we have
    another case 'kernel_install' can to this too, but this case has addational
    steps. In future, we will merge this to kernel_install case.

    1) Boot the vm
    2) Get latest kernel package link from brew
    3) Verify the version of guest kernel
    4) Compare guest kernel version and brew latest kernel version
    5) Backup boot cfg file
    6) Install guest kernel firmware (Optional)
    7) Install guest kernel
    8) Install guest kernel debuginfo (Optional)
    9) Backup boot cfg file after installing new kernel
    10) Installing virtio driver (Optional)
    11) Backup initrd file
    12) Update initrd file
    13) Make the new installed kernel as default
    14) Backup boot cfg file after setting new kernel as default
    15) Update the guest kernel cmdline (Optional)
    16) Reboot guest after updating kernel
    17) Verifying the virtio drivers (Optional)

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_brew_url(mnt_path, download_root):
        # get the url from the brew mnt path
        url = download_root + mnt_path[11:]
        logging.debug("Brew URL is %s" % url)
        return url

    def install_rpm(session, url, upgrade=False, nodeps=False, timeout=600):
        # install a package from brew
        cmd = "rpm -ivhf %s" % url
        if upgrade:
            # Upgrades or installs kernel to a newer version, then remove
            # old version.
            cmd = "rpm -Uvhf %s" % url
        if nodeps:
            cmd += " --nodeps"
        s, o = session.cmd_status_output(cmd, timeout=timeout)
        if s != 0 and ("already" not in o):
            raise error.TestFail("Fail to install %s:%s" % (url, o))

        return True
        # FIXME: need to add the check for newer version

    def copy_and_install_rpm(session, url, upgrade=False):
        rpm_name = os.path.basename(url)
        if url.startswith("http"):
            download_cmd = "wget %s" % url
            utils.system_output(download_cmd)
            rpm_src = rpm_name
        else:
            rpm_src = utils_misc.get_path(test.bindir, url)
        vm.copy_files_to(rpm_src, "/tmp/%s" % rpm_name)
        install_rpm(session, "/tmp/%s" % rpm_name, upgrade)

    def get_kernel_rpm_link():
        method = params.get("method", "link")
        if method not in ["link", "brew"]:
            raise error.TestError("Unknown installation method %s" % method)

        if method == "link":
            return (params.get("kernel_version"),
                    params.get("kernel_rpm"),
                    params.get("firmware_rpm"))

        error.context("Get latest kernel package link from brew", logging.info)
        # fetch the newest packages from brew
        # FIXME: really brain dead method to fetch the kernel version
        #        kernel_vesion = re... + hint from configuration file
        #        is there any smart way to fetch the `uname -r` from
        #        brew build?
        rh_kernel_hint = "[\d+][^\s]+"
        kernel_re = params.get("kernel_re")
        tag = params.get("brew_tag")

        latest_pkg_cmd = "brew latest-pkg %s kernel" % tag
        o = utils.system_output(latest_pkg_cmd, timeout=360)
        build = re.findall("kernel[^\s]+", o)[0]
        logging.debug("Latest package on brew for tag %s is %s" %
                      (tag, build))

        buildinfo = utils.system_output("brew buildinfo %s" % build,
                                        timeout=360)

        # install kernel-firmware
        firmware_url = None
        if "firmware" in buildinfo:
            logging.info("Found kernel-firmware")
            fw_pattern = ".*firmware.*"
            try:
                fw_brew_link = re.findall(fw_pattern, buildinfo)[0]
            except IndexError:
                raise error.TestError("Could not get kernel-firmware package"
                                      " brew link matching pattern '%s'" % fw_pattern)
            firmware_url = get_brew_url(fw_brew_link, download_root)

        knl_pattern = kernel_re % rh_kernel_hint
        try:
            knl_brew_link = re.findall(knl_pattern, buildinfo, re.I)[0]
        except IndexError:
            raise error.TestError("Could not get kernel package brew link"
                                  " matching pattern '%s'" % knl_pattern)
        kernel_url = get_brew_url(knl_brew_link, download_root)

        debug_re = kernel_re % ("(%s)" % rh_kernel_hint)
        try:
            kernel_version = re.findall(debug_re, kernel_url, re.I)[0]
        except IndexError:
            raise error.TestError("Could not get kernel version matching"
                                  " pattern '%s'" % debug_re)
        kernel_version += "." + params.get("kernel_suffix", "")

        return kernel_version, kernel_url, firmware_url

    def get_kernel_debuginfo_rpm_link():
        knl_dbginfo_re = params.get("knl_dbginfo_re")
        tag = params.get("brew_tag")

        latest_pkg_cmd = "brew latest-pkg %s kernel" % tag
        o = utils.system_output(latest_pkg_cmd, timeout=360)
        build = re.findall("kernel[^\s]+", o)[0]
        logging.debug("Latest package on brew for tag %s is %s" %
                      (tag, build))

        buildinfo = utils.system_output("brew buildinfo %s" % build,
                                        timeout=360)

        try:
            knl_dbginfo_links = re.findall(knl_dbginfo_re,
                                           buildinfo, re.I)
        except IndexError:
            raise error.TestError("Could not get kernel-debuginfo package "
                                  "brew link matching pattern '%s'" %
                                  knl_dbginfo_re)

        knl_dbginfo_urls = []
        for l in knl_dbginfo_links:
            link = get_brew_url(l, download_root)
            knl_dbginfo_urls.append(link)

        return knl_dbginfo_urls

    def get_guest_kernel_version():
        error.context("Verify the version of guest kernel", logging.info)
        s, o = session.cmd_status_output("uname -r")
        return o.strip()

    def is_kernel_debuginfo_installed():
        get_kernel_debuginfo_cmd = "rpm -qa | grep %s" % knl_dbginfo_version
        s, o = session.cmd_status_output(get_kernel_debuginfo_cmd)
        if s != 0:
            return False

        if knl_dbginfo_version not in o:
            logging.debug("%s has not been installed." % knl_dbginfo_version)
            return False

        logging.debug("%s has already been installed." % knl_dbginfo_version)

        return True

    def is_virtio_driver_installed():
        s, o = session.cmd_status_output("lsmod | grep virtio")
        if s != 0:
            return False

        for driver in virtio_drivers:
            if driver not in o:
                logging.debug("%s has not been installed." % driver)
                return False
            logging.debug("%s has already been installed." % driver)

        return True

    def compare_kernel_version(kernel_version, guest_version):
        error.context("Compare guest kernel version and brew's", logging.info)
        # return True: when kernel_version <= guest_version
        if guest_version == kernel_version:
            logging.info("The kernel version is matched %s" % guest_version)
            return True

        kernel_s = re.split('[.-]', kernel_version)
        guest_s = re.split('[.-]', guest_version)
        kernel_v = [int(i) for i in kernel_s if i.isdigit()]
        guest_v = [int(i) for i in guest_s if i.isdigit()]
        for i in range(min(len(kernel_v), len(guest_v))):
            if kernel_v[i] < guest_v[i]:
                logging.debug("The kernel version: '%s' is old than"
                              " guest version %s" % (kernel_version, guest_version))
                return True
            elif kernel_v[i] > guest_v[i]:
                return False

        if len(kernel_v) < len(guest_v):
            logging.debug("The kernel_version: %s is old than guest_version"
                          " %s" % (kernel_version, guest_version))
            return True

        return False

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
        pkgs = session.cmd_output(cmd).splitlines()
        pkgs.append(pkg)
        return pkgs

    def get_latest_pkgs_url(pkg, arch):
        """
        Get url of latest packages in brewweb.

        :parm pkg: package name without version info.
        :parm brew_tag:  requried in cfg file.
        :parm vm_arch_name: requried in cfg file.
        :parm latest_pkg_cmd: requried in cfg file.

        :return: urls for pkg in brewweb.
        :rtype: list
        """
        tag = params.get("brew_tag")
        latest_pkg_cmd = params.get("latest_pkg_cmd", "brew latest-pkg")
        latest_pkg_cmd = "%s %s %s" % (latest_pkg_cmd, tag, pkg)
        latest_pkg_cmd = "%s --arch=%s --paths" % (latest_pkg_cmd, arch)
        mnt_paths = utils.system_output(latest_pkg_cmd).splitlines()
        return [get_brew_url(_, download_root)
                for _ in mnt_paths if _.endswith(".rpm")]

    def upgrade_guest_pkgs(session, pkg, arch, debuginfo=False,
                           nodeps=True, timeout=600):
        """
        upgrade given packages in guest os.

        :parm session: session object.
        :parm pkg: package name without version info.
        :parm debuginfo: bool type, if True, install debuginfo package too.
        :parm nodeps: bool type, if True, ignore deps when install rpm.
        :parm timeout: float type, timeout value when install rpm.
        """
        error.context("Upgrade package '%s' in guest" % pkg, logging.info)
        pkgs = get_guest_pkgs(session, pkg, "%{NAME}")
        latest_pkgs_url = get_latest_pkgs_url(pkg, arch)
        for url in latest_pkgs_url:
            if "debuginfo" in url and not debuginfo:
                continue
            upgrade = bool(filter(lambda x: x in url, pkgs))
            logging.info("Install packages from: %s" % url)
            install_rpm(session, url, upgrade, nodeps, timeout)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    download_root = params["download_root_url"]
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    install_virtio = params.get("install_virtio", "yes")
    install_knl_debuginfo = params.get("install_knl_debuginfo")
    verify_virtio = params.get("verify_virtio", "yes")
    args_removed = params.get("args_removed", "").split()
    args_added = params.get("args_added", "").split()
    restore_initrd_cmd = ""
    virtio_drivers = params.get("virtio_drivers_list", "").split()
    kernel_version, kernel_rpm, firmware_rpm = get_kernel_rpm_link()
    knl_dbginfo_rpm = get_kernel_debuginfo_rpm_link()
    knl_dbginfo_version = "kernel-debuginfo-%s" % kernel_version

    logging.info("Kernel version:  %s" % kernel_version)
    logging.info("Kernel rpm    :  %s" % kernel_rpm)
    logging.info("Firmware rpm  :  %s" % firmware_rpm)

    boot_cfg_path = params.get("boot_cfg_path", "/boot/grub/grub.conf")
    bootcfg_backup_cmd = "\cp -af  {0} {0}-bk".format(boot_cfg_path)
    bootcfg_restore_cmd = "\cp -af {0}-bk {0}".format(boot_cfg_path)
    count = 0

    try:
        error.context("Backup '%s'" % boot_cfg_path)
        s, o = session.cmd_status_output(bootcfg_backup_cmd)
        if s != 0:
            raise error.TestError("Failed to backup '%s', guest output: '%s'"
                                  % (boot_cfg_path, o))
        count = 1

        # judge if need to install a new kernel
        ifupdatekernel = True
        guest_version = get_guest_kernel_version()
        if compare_kernel_version(kernel_version, guest_version):
            ifupdatekernel = False
            # set kernel_version to current version for later step to use
            kernel_version = guest_version

            if is_kernel_debuginfo_installed():
                install_knl_debuginfo = "no"

            if is_virtio_driver_installed():
                install_virtio = "no"
        else:
            logging.info("The guest kerenl is %s but expected is %s" %
                         (guest_version, kernel_version))

            rpm_install_func = install_rpm
            if params.get("install_rpm_from_local") == "yes":
                rpm_install_func = copy_and_install_rpm

            kernel_deps_pkgs = params.get("kernel_deps_pkgs", "dracut").split()
            if kernel_deps_pkgs:
                for pkg in kernel_deps_pkgs:
                    arch = params.get("arch_%s" % pkg,
                                      params.get("vm_arch_name"))
                    upgrade_guest_pkgs(session, pkg, arch)

            if firmware_rpm:
                error.context("Install guest kernel firmware", logging.info)
                rpm_install_func(session, firmware_rpm, upgrade=True)
            error.context("Install guest kernel", logging.info)
            status = rpm_install_func(session, kernel_rpm)
            if status:
                count = 2

            error.context("Backup '%s' after installing new kernel"
                          % boot_cfg_path, logging.info)
            s, o = session.cmd_status_output(bootcfg_backup_cmd)
            if s != 0:
                msg = ("Fail to backup '%s' after updating kernel,"
                       " guest output: '%s'" % (boot_cfg_path, o))
                logging.error(msg)
                raise error.TestError(msg)

        kernel_path = "/boot/vmlinuz-%s" % kernel_version

        if install_knl_debuginfo == "yes":
            error.context("Installing kernel-debuginfo packages", logging.info)

            links = ""

            for r in knl_dbginfo_rpm:
                links += " %s" % r

            install_rpm(session, links)

        if install_virtio == "yes":
            error.context("Installing virtio driver", logging.info)

            initrd_prob_cmd = "grubby --info=%s" % kernel_path
            s, o = session.cmd_status_output(initrd_prob_cmd)
            if s != 0:
                msg = ("Could not get guest kernel information,"
                       " guest output: '%s'" % o)
                logging.error(msg)
                raise error.TestError(msg)

            try:
                initrd_path = re.findall("initrd=(.*)", o)[0]
            except IndexError:
                raise error.TestError("Could not get initrd path from guest,"
                                      " guest output: '%s'" % o)

            driver_list = ["--with=%s " % drv for drv in virtio_drivers]
            mkinitrd_cmd = "mkinitrd -f %s " % initrd_path
            mkinitrd_cmd += "".join(driver_list)
            mkinitrd_cmd += " %s" % kernel_version
            cp_initrd_cmd = "\cp -af  %s %s-bk" % (initrd_path, initrd_path)
            restore_initrd_cmd = "\cp -af  %s-bk %s" % (initrd_path,
                                                        initrd_path)

            error.context("Backup initrd file")
            s, o = session.cmd_status_output(cp_initrd_cmd, timeout=200)
            if s != 0:
                logging.error("Failed to backup guest initrd,"
                              " guest output: '%s'", o)

            error.context("Update initrd file", logging.info)
            s, o = session.cmd_status_output(mkinitrd_cmd, timeout=360)
            if s != 0:
                msg = "Failed to install virtio driver, guest output '%s'" % o
                logging.error(msg)
                raise error.TestFail(msg)

            count = 3

        # make sure the newly installed kernel as default
        if ifupdatekernel:
            error.context("Make the new installed kernel as default",
                          logging.info)
            make_def_cmd = "grubby --set-default=%s " % kernel_path
            s, o = session.cmd_status_output(make_def_cmd)
            if s != 0:
                msg = ("Fail to set %s as default kernel,"
                       " guest output: '%s'" % (kernel_path, o))
                logging.error(msg)
                raise error.TestError(msg)

            count = 4
            error.context(
                "Backup '%s' after setting new kernel as default"
                % boot_cfg_path)
            s, o = session.cmd_status_output(bootcfg_backup_cmd)
            if s != 0:
                msg = ("Fail to backup '%s', guest output: '%s'"
                       % (boot_cfg_path, o))
                logging.error(msg)
                raise error.TestError(msg)

        # remove or add the required arguments

        error.context("Update the guest kernel cmdline", logging.info)
        remove_args_list = ["--remove-args=%s " % arg for arg in args_removed]
        update_kernel_cmd = "grubby --update-kernel=%s " % kernel_path
        update_kernel_cmd += "".join(remove_args_list)
        update_kernel_cmd += '--args="%s"' % " ".join(args_added)
        s, o = session.cmd_status_output(update_kernel_cmd)
        if s != 0:
            msg = "Fail to modify the kernel cmdline, guest output: '%s'" % o
            logging.error(msg)
            raise error.TestError(msg)

        count = 5

        # upgrade listed packages to latest version.
        for pkg in params.get("upgrade_pkgs", "").split():
            _ = params.object_params(pkg)
            arch = _.get("vm_arch_name", "x86_64")
            nodeps = _.get("ignore_deps") == "yes"
            install_debuginfo = _.get("install_debuginfo") == "yes"
            timeout = int(_.get("install_pkg_timeout", "600"))
            ver_before = session.cmd_output("rpm -q %s" % pkg)
            upgrade_guest_pkgs(
                session,
                pkg, arch,
                install_debuginfo,
                nodeps,
                timeout)
            ver_after = session.cmd_output("rpm -q %s" % pkg)
            if "not installed" in ver_before:
                mesg = "Install '%s' in guest" % ver_after
            else:
                mesg = "Upgrade '%s' from '%s'  to '%s'" % (pkg, ver_before, ver_after)
            logging.info(mesg)

        # reboot guest
        error.context("Reboot guest after updating kernel", logging.info)
        time.sleep(int(params.get("sleep_before_reset", 10)))
        session = vm.reboot(session, 'shell', timeout=login_timeout)
        # check if the guest can bootup normally after kernel update
        guest_version = get_guest_kernel_version()
        if guest_version != kernel_version:
            raise error.TestFail("Fail to verify the guest kernel, \n"
                                 "Expceted version %s \n"
                                 "In fact version %s \n" %
                                 (kernel_version, guest_version))

        if verify_virtio == "yes":
            error.context("Verifying the virtio drivers", logging.info)
            if not is_virtio_driver_installed():
                raise error.TestFail("Fail to verify the installation of"
                                     " virtio drivers")
    except Exception:
        if count in [4, 3, 1]:
            # restore boot cfg
            s, o = session.cmd_status_output(bootcfg_restore_cmd, timeout=100)
            if s != 0:
                logging.error("Failed to execute cmd '%s' in guest,"
                              " guest output: '%s'", bootcfg_restore_cmd, o)
        elif count == 2 and restore_initrd_cmd:
            # restore initrd file
            s, o = session.cmd_status_output(restore_initrd_cmd, timeout=200)
            if s != 0:
                logging.error("Failed to execute cmd '%s' in guest,"
                              " guest output: '%s'", restore_initrd_cmd, o)

        raise
