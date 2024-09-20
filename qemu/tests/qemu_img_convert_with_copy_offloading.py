from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img supports convert with copy-offloading.

    1. create source image, and  write "1" into
       the half of source image via qemu-io
    2. trace the system calls for qemu-img convert
       with copy-offloading and inspect whether
       there is copy_file_range
    3. compare the sourc and target images

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)

    def _convert_with_copy_offloading_and_verify(src, tgt):
        """Verify whether copy_offloading works."""
        test.log.info("Verify whether copy_offloading works for commit.")
        cmd = (
            "strace -e trace=copy_file_range -f qemu-img convert -C -f "
            "%s %s -O %s %s "
            % (
                src.image_format,
                src.image_filename,
                tgt.image_format,
                tgt.image_filename,
            )
        )
        sts, text = process.getstatusoutput(cmd, verbose=True)
        if sts != 0:
            test.fail("Convert with copy_offloading failed: %s." % text)

    src_image = params["src_image"]
    tgt_image = params["tgt_image"]
    img_dir = data_dir.get_data_dir()

    source = QemuImg(params.object_params(src_image), img_dir, src_image)
    source.create(source.params)
    _qemu_io(source, "write -P 1 0 %s" % params["write_size"])

    target = QemuImg(params.object_params(tgt_image), img_dir, tgt_image)
    _convert_with_copy_offloading_and_verify(source, target)
