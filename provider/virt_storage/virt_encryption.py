import json

from .virt_secret import secret_admin


class VolumeEncryption(object):
    def __init__(self, encrypt_format=None, secret=None):
        self.format = encrypt_format
        self.secret = secret

    def as_dict(self):
        return {"key-secret": self.secret.name, "format": self.format}

    def as_json(self):
        return json.dumps(self.as_dict())

    def __repr__(self):
        # return "json:%s" % json.dumps(self.as_dict())
        return "'%s'" % {"format": self.format, "key-secret": self.secret.name}

    def __str__(self):
        return "%s: %s" % (self.__class__.__name__, self.format)

    @classmethod
    def encryption_define_by_params(cls, params):
        instance = cls()
        if params["image_encryption"] == "on":
            encryption_format = "aes"
        else:
            encryption_format = params["image_encryption"]
        instance.format = encryption_format
        secret_name = params["secret_name"]
        secret = secret_admin.find_secret_by_name(secret_name)
        if not secret:
            secret_params = params.object_params(secret_name)
            secret = secret_admin.secret_define_by_params(secret_name, secret_params)
        instance.secret = secret
        return instance
