frappe.query_reports["Credit Sales"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_default("company"),
        },
        {
            fieldname: "credit_type",
            label: __("Credit Type"),
            fieldtype: "Select",
            options: ["", "Amount Pending", "Cylinder Pending", "Both Pending"],
        },
        {
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "Link",
            options: "Customer",
        },
        {
            fieldname: "location",
            label: __("Location"),
            fieldtype: "Link",
            options: "Gas Agency Location",
        },
        {
            fieldname: "broker",
            label: __("Broker"),
            fieldtype: "Link",
            options: "Broker",
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
        },
    ],
};
