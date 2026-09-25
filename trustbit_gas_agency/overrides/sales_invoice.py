import frappe
from trustbit_gas_agency.utils.cylinder_exchange import (
    process_cylinder_exchange,
    cancel_cylinder_exchange,
    validate_empties_not_received,
)


def validate(doc, method):
    validate_empties_not_received(doc)


def on_submit(doc, method):
    process_cylinder_exchange(doc, method)


def on_cancel(doc, method):
    cancel_cylinder_exchange(doc, method)
