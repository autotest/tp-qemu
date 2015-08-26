import logging
from autotest.client.shared import error
from qemu.tests import qemu_disk_img


class ResizeTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env):
        self.tag = params.get("image_resize", "image1")
        t_params = params.object_params(self.tag)
        super(ResizeTest, self).__init__(test, t_params, env, self.tag)

    def check_size(self, image_size, virtual_size):
        """
        Check the disk image size as if it had been change with resize;
        """
        re_size = self.params.get("re_size")
        human = {'B': 1,
                 'K': 1024,
                 'M': 1048576,
                 'G': 1073741824,
                 }
        if human.has_key(re_size[-1]):
            size = int(re_size[:-1]) * human[re_size[-1]]
            if "+" in re_size[0]:
                if virtual_size != image_size + size:
                    raise error.TestError("Check the image size failed!")
            elif "-" in re_size[0]:
                if virtual_size != image_size - size:
                    raise error.TestError("Check the image size failed!")
            else:
                if virtual_size != size:
                    raise error.TestError("Check the image size failed!")
        else:
            raise error.TestError("Invalid re_size: %s" % re_size)


def run(test, params, env):
    """
    'qemu-img' resize functions test:

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_file_name"]
    resize_test = ResizeTest(test, params, env)
    n_params = resize_test.create_snapshot()
    resize_test.start_vm(n_params)

    # save file md5sum before resize
    md5 = resize_test.save_file(t_file)
    if not md5:
        raise error.TestError("Fail to save tmp file")
    resize_test.destroy_vm()

    image_size = resize_test.get_size()
    virtual_size = resize_test.resize()
    resize_test.check_size(image_size, virtual_size)
    resize_test.check_image()

    # check md5sum after resize
    resize_test.start_vm(n_params)
    ret = resize_test.check_file(t_file, md5)
    if not ret:
        raise error.TestError("image content changed after resize")
    resize_test.clean()
