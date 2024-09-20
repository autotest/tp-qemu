import os

from avocado.utils import process
from virttest import data_dir, error_context
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg, get_image_repr

from provider.nbd_image_export import QemuNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Create a non-empty source qcow2 image and an empty destination image
    2) Export destination by nbd wrapped by the compress driver
    3) Copy src into destination then end qemu-nbd
    4) Check destination image is smaller (compressed)
    5) Check both images are identical (in content)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _write_to_image(img, write_size, write_timeout):
        """Writes data to the given image
        :param img: QemuImg instance which data will be written to
        :param write_size: amount of data written into target image
        :param write_timeout: maximum time for write command to complete
        """
        io_handler = QemuIOSystem(test, params, img.image_filename)
        test.log.info("Running qemu-io into %s", img.image_filename)
        try:
            io_handler.cmd_output(f"write -P 1 0 {write_size}", write_timeout)
        except process.CmdError:
            test.fail(f"Couldn't write to {img.image_filename} file by qemu-io")

    def _get_image_size(img, root_dir):
        """Returns size in bytes that the given image is actually using
        :param img: QemuImg instance of the image being checked
        :param root_dir: root data dir in which images are left
        :returns: an int with the disk usage of the image
        """
        img_path = os.path.join(root_dir, img.image_filename)
        try:
            res = process.run(f"ls -l {img_path}", shell=True).stdout_text
            # Taking 5.th element from output. Similar to '| awk...' but safer
            size = int(res.split()[4])
        except (process.CmdError, ValueError):
            test.error(f"Couldn't extract {img_path} size")
        except IndexError:
            test.error(f"cmd 'ls -l {img_path}' didn't work as expected")
        return size

    # Get references to the src and dst images (created in env preproc)
    images = params.get_list("images")
    if len(images) != 2:
        test.error(f"Test only supports 2 images but found {len(images)}.")
    (src, dst) = images
    root_dir = data_dir.get_data_dir()
    src_params = params.object_params(src)
    src_image = QemuImg(src_params, root_dir, src)
    dst_params = params.object_params(dst)
    dst_image = QemuImg(dst_params, root_dir, dst)
    # 1) Fill source image
    write_timeout = params.get_numeric("write_timeout", "120")
    write_size = params.get("write_size", "1G")
    _write_to_image(src_image, write_size, write_timeout)
    # 2) Export dst image by nbd
    test.log.info("Exporting NBD Image")
    nbd_export_filters = dst_params.get_list("nbd_export_filters")
    nbd_export_filter_ids = []
    for index, filter_type in enumerate(nbd_export_filters):
        nbd_export_filter_ids.append(f"filt{index}")
        dst_params[f"image_filter_driver_type_filt{index}"] = filter_type
    dst_params["image_filter_drivers"] = " ".join(nbd_export_filter_ids)
    dst_params["nbd_export_image_opts"] = get_image_repr(
        dst, dst_params, root_dir, "opts"
    )
    nbd_dst = QemuNBDExportImage(dst_params, dst)
    nbd_dst.export_image()
    # 3) Copy src into dst
    test.log.info("Executing source conversion onto remote target")
    try:
        src_image.convert(params, root_dir, skip_target_creation=True)
    except process.CmdError as exception_details:
        test.error(
            f"Couldn't convert {src} image onto {dst}."
            f"Have a look at:\n{exception_details}"
        )
    finally:
        # End qemu-nbd export in any case
        nbd_dst.stop_export()
    # 4) Check dst image is smaller than src
    test.log.info("Comparing src and dst image sizes")
    src_du = _get_image_size(src_image, root_dir)
    dst_du = _get_image_size(dst_image, root_dir)
    if src_du <= dst_du:
        # Assert dst size is smaller than src due to the compress driver
        test.fail(
            f"dst size is {dst_du} and src size is {src_du}.\nExpected "
            "dst to be smaller due to NBD compress driver."
        )
    # 5) Check src == dst in content
    test.log.info("Running qemu-img compare over the resulting local imgs")
    compare_res = src_image.compare_to(dst_image)
    if compare_res.exit_status:
        test.fail(
            f"src and dst images differ. {compare_res.stderr_text}"
            f"{compare_res.stdout_text}"
        )
