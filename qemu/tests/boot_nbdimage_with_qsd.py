import os

from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils
from provider.qsd import QsdDaemonDev


def run(test, params, env):
    """
    Boot nbd image with qsd plus unix.

    1) Prepare an installed OS image via converting
    2) Export the OS image via QSD plus unix
    3) Start VM from the exported image
    """

    def pre_test():
        # prepare an installed OS image
        test.log.info(
            "Prepare an installed OS image file via converting, "
            "and exporting it via QSD"
        )
        source = params["convert_source"]
        target = params["convert_target"]
        source_params = params.object_params(source)
        target_params = params.object_params(target)
        root_dir = data_dir.get_data_dir()
        source_image = qemu_storage.QemuImg(source_params, root_dir, source)
        target_image = qemu_storage.QemuImg(target_params, root_dir, target)

        test.log.info("Convert %s to %s", source, target)
        try:
            source_image.convert(params, root_dir)
        except process.CmdError as detail:
            target_image.remove()
            test.fail(
                "Convert %s to %s failed for '%s', check please."
                % (source, target, detail)
            )

        # export the OS image over QSD
        qsd.start_daemon()

    def run_test():
        # boot up a guest from the exported OS image
        test.log.info("Boot up a guest from the exported OS image.")
        login_timeout = params.get_numeric("login_timeout", 360)
        vm = None
        try:
            vm = img_utils.boot_vm_with_images(
                test, params, env, (params["nbd_image_tag"],)
            )
            vm.wait_for_login(timeout=login_timeout)
        finally:
            if vm:
                vm.destroy()

    def post_test():
        qsd.stop_daemon()

    # set socket path of the exporting image over nbd
    socket_path = os.path.join(data_dir.get_tmp_dir(), "nbd_stg1.sock")
    params["nbd_unix_socket_nbd1"] = socket_path
    params["qsd_image_export_nbd_stg1"] = '{"type":"unix","path":"%s"}' % socket_path

    qsd = QsdDaemonDev(params.objects("qsd_namespaces")[0], params)
    pre_test()
    try:
        run_test()
    finally:
        post_test()
