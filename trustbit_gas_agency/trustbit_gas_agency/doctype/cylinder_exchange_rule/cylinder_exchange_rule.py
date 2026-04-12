import frappe
from frappe import _
from frappe.model.document import Document


class CylinderExchangeRule(Document):
    def validate(self):
        if self.filled_item == self.empty_item:
            frappe.throw(_("Filled Cylinder Item and Empty Cylinder Item cannot be the same"))

        if self.exchange_ratio <= 0:
            frappe.throw(_("Exchange Ratio must be greater than 0"))

        if self.filled_weight_kg and self.filled_weight_kg < 0:
            frappe.throw(_("Filled Gas Weight cannot be negative"))

        if self.empty_weight_kg and self.empty_weight_kg < 0:
            frappe.throw(_("Empty Cylinder Weight cannot be negative"))
