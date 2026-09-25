from trustbit_gas_agency.utils.cylinder_exchange import cancel_empties_received


def on_cancel(doc, method):
    cancel_empties_received(doc, method)
