"""What a browser sends to the cookie-authenticated /v1/auth/* endpoints.

`shared/origin_guard.py` refuses those requests unless they carry an `Origin` we trust, so a
test that drives them through the handler has to look like one. `tests/conftest.py` trusts
BROWSER_ORIGIN for every test; the tests of the guard itself set their own.
"""

BROWSER_ORIGIN = "https://app.shipx.test"
# Header names are lowercase: API Gateway's payload format 2.0 lowercases them.
BROWSER_HEADERS = {"origin": BROWSER_ORIGIN, "content-type": "application/json"}
