# Hardened subscription — holds staging, demo and prod.
#
# Every Defender plan on, paid and unpaid: these three environments are
# non-negotiable. Expect roughly $40–60/month of Defender charges for the
# current resource count, plus per-GB malware scanning up to the cap below.
subscription_name = "hardened"

enable_paid_defender_plans = true

security_contact_email = "ifexalex2@gmail.com"

# Cap malware scanning per storage account per month. Raise only after looking
# at actual upload volume — manifests and claim photos are small, so the default
# is far above expected usage and exists to bound a runaway.
malware_scanning_cap_gb_per_month = 500
