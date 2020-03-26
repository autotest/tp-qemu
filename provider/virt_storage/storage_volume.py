from virttest import utils_misc
from virttest.qemu_devices import qdevices

from provider import backup_utils
from . import virt_encryption


class StorageVolume(object):

    def __init__(self, pool):
        self.name = None
        self.pool = pool
        self._url = None
        self._path = None
        self._capacity = None
        self._key = None
        self._auth = None
        self._format = None
        self._protocol = None
        self.is_allocated = None
        self.preallocation = None
        self.backing = None
        self.encrypt = None
        self.used_by = []
        self.pool.add_volume(self)
        self._params = None

    @property
    def url(self):
        if self._url is None:
            if self.name and hasattr(self.pool.helper, "get_url_by_name"):
                url = self.pool.helper.get_url_by_name(self.name)
                self._url = url
        return self._url

    @url.setter
    def url(self, url):
        self._url = url

    @property
    def path(self):
        if self._path is None:
            if self.url and hasattr(self.pool.helper, "url_to_path"):
                path = self.pool.helper.url_to_path(self.url)
                self._path = path
        return self._path

    @path.setter
    def path(self, path):
        self._path = path

    @property
    def key(self):
        if self._key is None:
            if self.pool.TYPE in ("directory", "nfs"):
                self._key = self.path
            else:
                self._key = self.url
        return self._key

    @key.setter
    def key(self, key):
        self._key = key

    @property
    def format(self):
        if self._format is None:
            self._format = qdevices.QBlockdevFormatQcow2(self.name)
        return self._format

    @format.setter
    def format(self, format):
        if format == "qcow2":
            format_cls = qdevices.QBlockdevFormatQcow2
        else:
            format_cls = qdevices.QBlockdevFormatRaw
        self._format = format_cls(self.name)

    @property
    def protocol(self):
        if self._protocol is None:
            if self.pool.TYPE == "directory":
                self._protocol = qdevices.QBlockdevProtocolFile(self.name)
            else:
                raise NotImplementedError
        return self._protocol

    @property
    def capacity(self):
        if self._capacity is None:
            if self.key and hasattr(self.pool.helper, "get_size"):
                self._capacity = self.pool.get_size(self.key)
        if self._capacity is None:
            self._capacity = 0
        return int(self._capacity)

    @capacity.setter
    def capacity(self, size):
        self._capacity = float(
            utils_misc.normalize_data_size(
                str(size), 'B', '1024'))

    @property
    def auth(self):
        if self._auth is None:
            if self.pool.source:
                self._auth = self.pool.source.auth
        return self._auth

    def refresh_with_params(self, params):
        self._params = params
        self.format = params.get("image_format", "qcow2")
        self.capacity = params.get("image_size", "100M")
        self.preallocation = params.get("preallocation", "off")
        self.refresh_protocol_by_params(params)
        self.refresh_format_by_params(params)
        if self.pool.TYPE == "directory":
            volume_params = params.object_params(self.name)
            self.path = self.pool.get_volume_path_by_param(volume_params)
        else:
            raise NotImplementedError

    def refresh_format_by_params(self, params):
        if self.format.TYPE == "qcow2":
            encrypt = params.get("image_encryption")
            if encrypt and encrypt != "off":
                self.encrypt = virt_encryption.VolumeEncryption.encryption_define_by_params(
                    params)
                self.format.set_param(
                    "encrypt.key-secret",
                    self.encrypt.secret.name)
                self.format.set_param("encrypt.format", self.encrypt.format)

            backing = params.get("backing")
            if backing:
                backing_node = "drive_%s" % backing
                self.format.set_param("backing", backing_node)
        self.format.set_param("file", self.protocol.get_param("node-name"))

    def refresh_protocol_by_params(self, params):
        if self.protocol.TYPE == "file":
            aio = params.get("image_aio", "threads")
            self.protocol.set_param("filename", self.path)
            self.protocol.set_param("aio", aio)
        else:
            raise NotImplementedError

    def info(self):
        out = dict()
        out["name"] = self.name
        out["pool"] = str(self.pool)
        out["url"] = self.url
        out["path"] = self.path
        out["key"] = self.key
        out["format"] = self.format.TYPE
        out["auth"] = str(self.auth)
        out["capacity"] = self.capacity
        out["preallocation"] = self.preallocation
        out["backing"] = str(self.backing)
        return out

    def generate_qemu_img_options(self):
        options = " -f %s" % self.format.TYPE
        if self.format.TYPE == "qcow2":
            backing_store = self.backing
            if backing_store:
                options += " -b %s" % backing_store.key
            encrypt = self.format.get_param("encrypt")
            if encrypt:
                secret = encrypt.secret
                options += " -%s " % secret.as_qobject().cmdline()
                options += " -o encrypt.format=%s,encrypt.key-secret=%s" % (
                    encrypt.format, secret.name)
        return options

    def hotplug(self, vm):
        if not self.pool.is_running():
            self.pool.start_pool()
        protocol_node = self.protocol
        self.create_protocol_by_qmp(vm)
        cmd, options = protocol_node.hotplug_qmp()
        vm.monitor.cmd(cmd, options)
        format_node = self.format
        self.format_protocol_by_qmp(vm)
        cmd, options = format_node.hotplug_qmp()
        vm.monitor.cmd(cmd, options)
        self.pool.refresh()

    def create_protocol_by_qmp(self, vm, timeout=120):
        node_name = self.protocol.get_param("node-name")
        options = {"driver": self.protocol.TYPE}
        if self.protocol.TYPE == "file":
            options["filename"] = self.protocol.get_param("filename")
            options["size"] = self.capacity
        else:
            raise NotImplementedError
        arguments = {
            "options": options,
            "job-id": node_name,
            "timeout": timeout}
        return backup_utils.blockdev_create(vm, **arguments)

    def format_protocol_by_qmp(self, vm, timeout=120):
        node_name = self.format.get_param("node-name")
        options = {"driver": self.format.TYPE,
                   "file": self.protocol.get_param("node-name"),
                   "size": self.capacity}
        if self.format.TYPE == "qcow2":
            if self.backing:
                options["backing-fmt"] = self.backing.format.TYPE
                options["backing-file"] = self.backing.path
            if self.encrypt:
                options["encrypt"] = dict()
                key_secret = self.format.get_param("encrypt.key-secret")
                if key_secret:
                    options["encrypt"]["key-secret"] = key_secret
                encrypt_format = self.format.get_param("encrypt.format")
                if encrypt_format:
                    options["encrypt"]["format"] = encrypt_format
            if self._params and self._params.get("image_cluster_size"):
                options["cluster-size"] = int(
                    self._params["image_cluster_size"])
        arguments = {
            "options": options,
            "job-id": node_name,
            "timeout": timeout}
        backup_utils.blockdev_create(vm, **arguments)

    def __str__(self):
        return "%s-%s(%s)" % (self.__class__.__name__,
                              self.name, str(self.key))

    def __eq__(self, vol):
        if not isinstance(vol, StorageVolume):
            return False
        else:
            return self.info() == vol.info()

    def __hash__(self):
        return hash(str(self.info()))

    def __repr__(self):
        return "'%s'" % self.name

    def as_json(self):
        _, options = self.format.hotplug_qmp()
        return "json: %s" % options

    def remove(self):
        return self.pool.remove_volume(self)
