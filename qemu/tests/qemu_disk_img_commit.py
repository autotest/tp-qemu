import logging

from avocado.utils import process

from virttest import error_context

from qemu.tests import qemu_disk_img


class CommitTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env):
        self.tag = params.get("image_commit", "image1")
        t_params = params.object_params(self.tag)
        super(CommitTest, self).__init__(test, t_params, env, self.tag)

    @error_context.context_aware
    def commit(self, t_params=None):
        """
        commit snapshot to backing file;
        """
        error_context.context("commit snapshot to backingfile", logging.info)
        params = self.params.object_params(self.tag)
        if t_params:
            params.update(t_params)
        cache_mode = params.get("cache_mode")
        return super(CommitTest, self).commit(params, cache_mode)


@error_context.context_aware
def run(test, params, env):
    """
    'qemu-img' commit functions test:

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_file_name"]
    commit_test = CommitTest(test, params, env)
    n_params = commit_test.create_snapshot()
    commit_test.start_vm(n_params)

    # save file md5sum before commit
    md5 = commit_test.save_file(t_file)
    if not md5:
        test.error("Fail to save tmp file")
    commit_test.destroy_vm()
    commit_test.commit()
    error_context.context("sync host data after commit", logging.info)
    process.system("sync")
    commit_test.start_vm(params)

    # check md5sum after commit
    ret = commit_test.check_file(t_file, md5)
    if not ret:
        test.error("image content changed after commit")
    commit_test.clean()
