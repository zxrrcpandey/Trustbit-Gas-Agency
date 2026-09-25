import re

from frappe.model.document import Document


class GasVehicle(Document):
    def before_naming(self):
        # "mp 09 ab-1234" and "MP09AB1234" must be the same vehicle
        self.vehicle_number = re.sub(r"[\s-]", "", self.vehicle_number or "").upper()
