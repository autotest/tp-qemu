import logging

from avocado.core import exceptions
from avocado.utils import process
from virttest import error_context, storage

from qemu.tests import qemu_disk_img

LOG_JOB = logging.getLogger("avocado.test")


class ConvertTest(qemu_disk_img.QemuImgTest):
    def __init__(self, test, params, env):
        self.tag = params["convert_source"]
        t_params = params.object_params(self.tag)
        super(ConvertTest, self).__init__(test, t_params, env, self.tag)

    @error_context.context_aware
    def convert(self, t_params=None):
        """
        create image file from one format to another format
        """
        error_context.context("convert image file", LOG_JOB.info)
        params = self.params.object_params(self.tag)
        if t_params:
            params.update(t_params)
        cache_mode = params.get("cache_mode")
        conv = super(ConvertTest, self).convert(params, self.data_dir, cache_mode)
        params = params.object_params(conv)
        converted = storage.get_image_filename(params, self.data_dir)
        process.run("sync")
        self.trash.append(converted)
        return params

    @error_context.context_aware
    def compare_test(self, t_params):
        """
        Compare images.

        :param t_params: Dictionary with the test parameters
        """
        for mode in t_params.objects("compare_mode_list"):
            error_context.context("Compare images in %s mode" % mode, LOG_JOB.info)
            cmd_result = None
            is_strict = "strict" == mode
            image1 = self.image_filename
            image2 = storage.get_image_filename(t_params, self.data_dir)
            try:
                cmd_result = self.compare_images(image1, image2, is_strict)
            except (exceptions.TestFail, exceptions.TestError):
                if not is_strict:
                    raise
            if is_strict and cmd_result:
                self.test.fail("images are identical in strict mode")


def run(test, params, env):
    """
    'qemu-img' convert functions test:

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {
            "image_name_%s" % base_image: params["image_name"],
            "image_format_%s" % base_image: params["image_format"],
        }
    )
    t_file = params["guest_file_name"]
    convert_test = ConvertTest(test, params, env)
    n_params = convert_test.create_snapshot()
    convert_test.start_vm(n_params)

    # save file md5sum before conversion
    md5 = convert_test.save_file(t_file)
    if not md5:
        test.error("Fail to save tmp file")
    convert_test.destroy_vm()

    cluster_size_lst = params.get("cluster_size_set", "").split()
    if not cluster_size_lst:
        cluster_size_lst.append(None)
    for cluster_size in cluster_size_lst:
        if cluster_size is not None:
            test.log.info("convert image file with cluster_size=%s.", cluster_size)
        n_params = convert_test.convert({"image_cluster_size": cluster_size})
        convert_test.compare_test(n_params)
        convert_test.verify_info(n_params)
        convert_test.start_vm(n_params)
        # check md5sum after conversion
        if not convert_test.check_file(t_file, md5):
            test.error("image content changed after convert")
        convert_test.clean()
