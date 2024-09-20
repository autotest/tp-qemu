import os

from avocado.utils import process


class RBDCli(object):
    def __init__(self, pool_name):
        self.pool_name = pool_name
        self._protocol = r"rbd:"
        self._is_export = None

    @staticmethod
    def remove_image(path):
        return process.system("rbd rm %s" % path, shell=True)

    def get_path_by_name(self, name):
        path = os.path.join(self.pool_name, name)
        return path

    def get_url_by_name(self, name):
        path = self.get_path_by_name(name)
        return self.path_to_url(path)

    def list_images(self):
        """List all images"""
        cmd = "rbd ls %s" % self.pool_name
        images = process.system_output(cmd).decode().split()
        return images

    def path_to_url(self, path):
        """Get url schema path"""
        return "%s%s" % (self._protocol, path)

    def url_to_path(self, url):
        return url[len(self._protocol) :]
