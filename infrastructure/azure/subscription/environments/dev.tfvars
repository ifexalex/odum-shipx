# Dev subscription — free controls only.
#
# enable_paid_defender_plans stays FALSE here and that is the entire reason dev
# needs its own subscription: Defender is billed per subscription, so leaving dev
# alongside staging/demo/prod would bill dev for plans it is exempt from.
subscription_name = "dev"

enable_paid_defender_plans = false

# Free in every subscription: without a contact, high-severity alerts are raised
# and then go nowhere.
security_contact_email = "ifexalex2@gmail.com"
