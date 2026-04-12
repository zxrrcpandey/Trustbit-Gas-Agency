import frappe
from frappe.model.document import Document


class GasAgencyLocation(Document):
    def validate(self):
        if self.default_target_warehouse and self.warehouse == self.default_target_warehouse:
            frappe.throw(
                "Empty Cylinder Warehouse must be different from the primary Warehouse"
            )
