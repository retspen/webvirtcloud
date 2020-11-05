import base64

from vrtManager.connection import wvmConnect


class wvmSecrets(wvmConnect):
    def create_secret(self, ephemeral, private, secret_type, data):
        xml = f"""<secret ephemeral='{ephemeral}' private='{private}'>
                    <usage type='{secret_type}'>"""
        if secret_type == "ceph":
            xml += f"""<name>{data}</name>"""
        if secret_type == "volume":
            xml += f"""<volume>{data}</volume>"""
        if secret_type == "iscsi":
            xml += f"""<target>{data}</target>"""
        xml += """</usage>
                 </secret>"""
        self.wvm.secretDefineXML(xml)

    def get_secret_value(self, uuid):
        secrt = self.get_secret(uuid)
        value = secrt.value()
        return base64.b64encode(value)

    def set_secret_value(self, uuid, value):
        secrt = self.get_secret(uuid)
        value = base64.b64decode(value)
        secrt.setValue(value)

    def delete_secret(self, uuid):
        secrt = self.get_secret(uuid)
        secrt.undefine()
