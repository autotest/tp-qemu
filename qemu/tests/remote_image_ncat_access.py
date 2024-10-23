import socket

from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage, storage

from provider import qemu_img_utils as img_utils
from provider.nbd_image_export import InternalNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Clone system image with qemu-img
    2) Export the image with qemu internal NBD server
    3) ncate ip -p port or ncat -U /socket/path
    4) Boot from the exported nbd image
    5) Log into VM

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _create_image():
        result = qemu_storage.QemuImg(params, None, params["images"].split()[0]).dd(
            output=storage.get_image_filename(
                params.object_params(params["local_image_tag"]), data_dir.get_data_dir()
            ),
            bs=1024 * 1024,
        )

        if result.exit_status != 0:
            test.fail(
                "Failed to clone the system image, error: %s" % result.stderr.decode()
            )

    def _start_vm_without_image():
        params["images"] = ""
        vm = None
        try:
            vm = img_utils.boot_vm_with_images(test, params, env)
            vm.verify_alive()
        finally:
            # let VT remove it
            params["images"] = " %s" % params["local_image_tag"]
        return vm

    def _make_ncat_cmd():
        ncat = ""
        if params.get("nbd_unix_socket_%s" % params["nbd_image_tag"]):
            ncat = params["ncat_cmd"]
        else:
            localhost = socket.gethostname()
            params["nbd_server"] = localhost if localhost else "localhost"
            ncat = params["ncat_cmd"].format(localhost=params["nbd_server"])
        return ncat

    _create_image()
    vm = _start_vm_without_image()

    nbd_export = InternalNBDExportImage(vm, params, params["local_image_tag"])
    nbd_export.hotplug_tls()
    nbd_export.hotplug_image()
    nbd_export.export_image()
    params["nbd_export_name"] = nbd_export.get_export_name()

    ncat_cmd = _make_ncat_cmd()
    result = process.run(ncat_cmd, ignore_status=True, shell=True)
    if params["errmsg_check"] not in result.stderr.decode().strip():
        test.fail(
            "Failed to read message(%s) from output(%s)"
            % (params["errmsg_check"], result.stderr.decode())
        )

    vm2 = None
    try:
        # Start another VM from the nbd exported image
        vm2 = img_utils.boot_vm_with_images(
            test, params, env, (params["nbd_image_tag"],), "vm2"
        )
        session = vm2.wait_for_login(timeout=params.get_numeric("login_timeout", 480))
        session.close()
    finally:
        if vm2:
            vm2.destroy()
