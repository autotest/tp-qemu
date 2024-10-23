from virttest import (
    data_dir,
    error_context,
    qemu_storage,
    storage,
    utils_disk,
    utils_numeric,
)
from virttest.qemu_monitor import QMPCmdError

from provider.qsd import QsdDaemonDev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Export a luks image via QSD with NBD inet.
    1. Create a luks image.
    2. Start a QSD daemon, and export the luks image with NBD inet.
    3. Check the info of the image over NBD.
    4. Boot up a guest with the exported image as a data disk.
    5. Check there is the data disk in the guest.
    6. Connect to the QMP sock
    6.1 Query the block exports
    6.2 luks key management
    7. Stop the QSD daemon
    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def pre_test():
        qsd.start_daemon()

    def check_disk(image_params):
        luks_image_size = image_params["image_size"]
        login_timeout = params.get_numeric("login_timeout", 360)
        vm = env.get_vm(params["main_vm"])
        try:
            vm.create()
            vm.verify_alive()
            session = vm.wait_for_login(timeout=login_timeout)
            disks = utils_disk.get_linux_disks(session, True)
            session.close()
            for _, attr in disks.items():
                if "disk" in attr and luks_image_size in attr:
                    break
            else:
                test.fail("Failed to find the luks image in guest")
        finally:
            vm.destroy()

    def querey_block_exports(image_params):
        luks_image_size = image_params["image_size"]

        out = qsd.monitor.cmd("query-block-exports")[0]
        if out.get("type") != "nbd":
            test.fail("The exported type is not matched to 'nbd'.")
        out = qsd.monitor.cmd("query-named-block-nodes")[0]
        image_info = out.get("image")
        image_size = (
            utils_numeric.normalize_data_size(
                str(image_info.get("virtual-size")), "G"
            ).split(".")[0]
            + "G"
        )
        image_name = image_info.get("filename")
        expected_image_name = storage.get_image_filename(
            image_params, data_dir.get_data_dir()
        )
        if image_size != luks_image_size or image_name != expected_image_name:
            test.fail(
                "The image size(%s) or image name(%s) is not matched to the "
                "original image." % (image_size, image_name)
            )

    def hotplug_secret_objects():
        args1 = {"qom-type": "secret", "id": "sec1", "data": "redhat1"}
        args2 = {"qom-type": "secret", "id": "sec2", "data": "redhat2"}
        for args in [args1, args2]:
            out = qsd.monitor.cmd("object-add", args)
            if "error" in out:
                test.fail("Add secret object failed, check please")
        args = {
            "node-name": "fmt_stg1",
            "job-id": "job_add_key1",
            "options": {
                "driver": "luks",
                "state": "active",
                "new-secret": "sec1",
                "keyslot": 1,
                "iter-time": 10,
            },
        }
        try:
            qsd.monitor.cmd("x-blockdev-amend", args)
        except QMPCmdError as e:
            qmp_error_msg = params.get("qmp_error_msg")
            if qmp_error_msg not in str(e.data):
                test.fail("The error msg(%s) is not correct." % str(e))
        else:
            test.fail("Unexpected success when running x-blockdev-amend")

    def run_test():
        luks_img_param = params.object_params("stg1")
        nbd_image_tag = params["nbd_image_tag"]
        nbd_image_params = params.object_params(nbd_image_tag)
        qemu_img = qemu_storage.QemuImg(nbd_image_params, None, nbd_image_tag)
        qemu_img.info()

        check_disk(luks_img_param)
        querey_block_exports(luks_img_param)
        hotplug_secret_objects()

    def post_test():
        qsd.stop_daemon()

    qsd = QsdDaemonDev(params.objects("qsd_namespaces")[0], params)
    pre_test()
    try:
        run_test()
    finally:
        post_test()
