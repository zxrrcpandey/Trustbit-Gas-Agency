app_name = "trustbit_gas_agency"
app_title = "Trustbit Gas Agency"
app_publisher = "Trustbit Software"
app_description = "Gas Agency Management for Cylinder Exchange and Multi-Location Tracking"
app_email = "info@trustbit.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/trustbit_gas_agency/css/trustbit_gas_agency.css"
# app_include_js = "/assets/trustbit_gas_agency/js/trustbit_gas_agency.js"

# DocType JS extensions
doctype_js = {
    "Sales Invoice": "public/js/sales_invoice.js",
    "Delivery Note": "public/js/delivery_note.js",
}

# Document Events
doc_events = {
    "Sales Invoice": {
        "on_submit": "trustbit_gas_agency.overrides.sales_invoice.on_submit",
        "on_cancel": "trustbit_gas_agency.overrides.sales_invoice.on_cancel",
    },
    "Delivery Note": {
        "on_submit": "trustbit_gas_agency.overrides.delivery_note.on_submit",
        "on_cancel": "trustbit_gas_agency.overrides.delivery_note.on_cancel",
    },
    "Payment Entry": {
        "validate": "trustbit_gas_agency.overrides.payment_entry.validate",
    },
}

# Fixtures
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "Trustbit Gas Agency"]],
    }
]
