environment  = "staging"
location     = "northeurope"
api_base_url = "https://api-staging.shipx.example"

# Non-production recipient guard (shared/notifications.is_recipient_allowed).
# Fails CLOSED: empty means every notification is suppressed. Staging, like dev,
# can hold real customer contacts imported from client manifests, so only real
# test contacts belong here. Match is an exact, case-insensitive compare and
# phones are stored E.164 (shared/phone.py), so use the +234 form.
notification_allowlist = "+2348169760253"
