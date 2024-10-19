"""QSD installation test"""

from virttest.tests import unattended_install

from provider.qsd import QsdDaemonDev, add_vubp_into_boot


def run(test, params, env):
    """
    Test installation test .
    Steps:
        1) Run QSD with one export vhost-user-blk.
        2) Boot VM with vhost-user-blk-pci device and install media.
        3) Wait for installation finish
        4) Login guest and run check command
    """

    logger = test.log
    qsd = None

    try:
        qsd_name = params["qsd_namespaces"]
        qsd = QsdDaemonDev(qsd_name, params)
        qsd.start_daemon()
        img = params["qsd_images_qsd1"]
        add_vubp_into_boot(img, params, 6)

        logger.debug("unattended_install start")
        unattended_install.run(test, params, env)
        logger.debug("Finish installation")
        vm = env.get_vm(params.get("main_vm"))
        vm.destroy()
        logger.debug("Reboot...")
        params["cdroms"] = ""
        params["start_vm"] = "yes"
        params["cdrom_unattended"] = ""
        params["kernel"] = ""
        params["initrd"] = ""
        params["boot_once"] = "c"
        params["kernel_params"] = ""
        vm.create(params=params)
        vm.verify_alive()
        logger.debug("Login guest ...")
        session = vm.wait_for_login()
        session.cmd(params["guest_cmd"])
        logger.debug("Exit guest ...")
        vm.destroy()
        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()
