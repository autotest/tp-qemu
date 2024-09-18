import json
import logging

from avocado.utils import process
from virttest.data_dir import get_data_dir
from virttest.qemu_devices.qdevices import QBlockdevFormatNode
from virttest.qemu_storage import QemuImg, get_image_json, get_image_repr

LOG_JOB = logging.getLogger("avocado.test")


def run(test, params, env):
    """
    KVM migration test:
    1) Create a snapshot chain base->sn1->sn2 with backing:json format.
    2) Start src guest with sn2.
    3) Start dst guest with sn2 and listening status.
    4) Do migration from src to dst.
    5) After migration finished, continue vm in dst.
    6) In dst, do snapshot from sn2 to sn3
    7) Check sn3 backing chain by qemu-img info

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_img_objs(images):
        return [
            QemuImg(params.object_params(tag), get_data_dir(), tag) for tag in images
        ]

    def _create_image_with_backing(image):
        secids = [s.image_id for s in image.encryption_config.base_key_secrets]
        if image.base_tag in secids:
            image.create(params)
        else:
            base_params = params.object_params(image.base_tag)
            backing_file = "'%s'" % get_image_json(
                image.base_tag, base_params, get_data_dir()
            )
            cmd = "{cmd} create -F {base_fmt} -b {backing} -f {fmt} {f} {size}"
            qemu_img_cmd = cmd.format(
                cmd=image.image_cmd,
                base_fmt=base_params["image_format"],
                backing=backing_file,
                fmt=image.image_format,
                f=image.image_filename,
                size=image.size,
            )

            msg = "Create image by command: %s" % qemu_img_cmd
            LOG_JOB.info(msg)
            process.run(qemu_img_cmd, shell=True, verbose=False, ignore_status=False)

    def src_sn_chain_setup(image_objects):
        for image in image_objects[1 : len(image_objects) - 1]:
            _create_image_with_backing(image)

    def blockdev_add_image(tag):
        image_params = params.object_params(tag)
        devices = vm.devices.images_define_by_params(tag, image_params, "disk")
        devices.pop()
        for dev in devices:
            if vm.devices.get_by_qid(dev.get_qid()):
                continue
            if isinstance(dev, QBlockdevFormatNode):
                dev.params["backing"] = None
            ret = vm.devices.simple_hotplug(dev, vm.monitor)
            if not ret[1]:
                test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def create_snapshot():
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        arguments = params.copy_from_keys(options)
        arguments.setdefault("node", "drive_%s" % params["base_tag"])
        arguments.setdefault("overlay", "drive_%s" % params["snapshot_tag"])
        return vm.monitor.cmd(cmd, dict(arguments))

    def verify_backing_chain(info):
        """Verify image's backing chain."""
        for image, img_info in zip(images, reversed(info)):
            base_image = None
            if image.base_tag:
                base_params = params.object_params(image.base_tag)
                base_image = get_image_repr(
                    image.base_tag, base_params, get_data_dir(), "filename"
                )
            backing_info = img_info.get("full-backing-filename")
            if backing_info and "json" in backing_info:
                back_info = backing_info.strip("json:")
                backing_info = json.loads(back_info)["file"]["filename"]
            if base_image != backing_info:
                test.fail(
                    (
                        "backing chain check for image %s failed, backing"
                        " file from info is %s, which should be %s."
                    )
                    % (image.image_filename, backing_info, base_image)
                )

    def check_backing_file(image):
        out = json.loads(image.info(force_share=True, output="json"))
        verify_backing_chain(out)

    def clean_images(image_objects):
        for image in image_objects:
            image.remove()

    images_tag = params.get("image_chain").split()
    params["image_name_%s" % images_tag[0]] = params["image_name"]
    images = get_img_objs(images_tag)
    try:
        src_sn_chain_setup(images)
        vm = env.get_vm(params["main_vm"])
        vm.params["images"] = images_tag[-2]
        vm.create()
        for item in vm.devices.temporary_image_snapshots:
            if images_tag[-2] in item:
                vm.devices.temporary_image_snapshots.remove(item)
                break
        vm.migrate()
        snapshot_tag = params.get("snapshot_tag")
        snapshot_image = images[-1]
        snapshot_image.create(params)
        blockdev_add_image(snapshot_tag)
        create_snapshot()
        check_backing_file(snapshot_image)
    finally:
        clean_images(images[1:])
