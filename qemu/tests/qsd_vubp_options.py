"""QSD vhost-user-blk-pci device options test"""

from virttest import env_process, utils_disk, utils_misc

from provider.qsd import QsdDaemonDev, add_vubp_into_boot


def run(test, params, env):
    """
    QSD vhost-user-blk-pci device options test.
    Steps:
        1) Run QSD with one export vhost-user-blk.
        2) Boot VM with vhost-user-blk-pci device and specified options
        3) Check disk existence and execute IO on it
    """

    def _get_disk_by_size(img_tag, check_exist_flag=None):
        disk_params = params.object_params(img_tag)
        disk_size = disk_params["image_size"]
        os_type = params["os_type"]
        disk = None
        if os_type != "windows":
            disks = utils_disk.get_linux_disks(session, True)
            for kname, attr in disks.items():
                if attr[1] == disk_size and attr[2] == "disk":
                    disk = kname
                    break
        else:
            disks = utils_disk.get_windows_disks_index(session, disk_size)
            disk = disks[0] if disks else None

        if check_exist_flag is not None:
            if bool(disk) != check_exist_flag:
                test.fail("Disk should exist %s" % check_exist_flag)
        logger.debug("Find disk is:%s", disk)
        return disk

    def _configure_disk(img_tag):
        disk_params = params.object_params(img_tag)
        disk_size = disk_params["image_size"]
        guest_cmd = params["guest_cmd"]
        disk_id = _get_disk_by_size(img_tag, True)
        logger.debug(disk_id)

        os_type = params["os_type"]
        if os_type != "windows":
            driver = utils_disk.configure_empty_linux_disk(session, disk_id, disk_size)[
                0
            ]
            logger.debug("mount_point is %s", driver)
            output_path = r"%s/test.dat" % driver
        else:
            guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            utils_disk.update_windows_disk_attributes(session, disk_id)
            driver = utils_disk.configure_empty_windows_disk(
                session, disk_id, disk_size
            )[0]
            output_path = r"%s:\\test.dat" % driver

        guest_cmd = guest_cmd % output_path
        session.cmd(guest_cmd)

    logger = test.log
    qsd = None
    try:
        qsd_name = params["qsd_namespaces"]
        qsd = QsdDaemonDev(qsd_name, params)
        qsd.start_daemon()
        img = params["qsd_images_%s" % qsd_name]
        add_vubp_into_boot(img, params, 6)

        params["start_vm"] = "yes"

        login_timeout = params.get_numeric("login_timeout", 360)
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        logger.debug("Check disk...")
        session = vm.wait_for_login(timeout=login_timeout)

        _configure_disk(img)

        logger.debug("VM destroy...")
        vm.destroy()
        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()
