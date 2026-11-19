"""Contracts between the application code and the Terraform that deploys it.

scripts/local_server.py routes every request by path prefix, so a route that
was never declared in API Gateway, a Lambda pointed at a handler function that
doesn't exist, or a route whose service has no deployed Lambda behind it all
work perfectly in local dev and fail only in AWS. These checks parse the
Terraform and application sources directly (no AWS, no `terraform` binary) so
that drift is caught in CI instead of at deploy time.

Found by audit 2026-09-23: ~80 served routes missing from API Gateway
(including every /v1/notifications/* route), all notification Lambdas pointed
at a nonexistent `lambda_handler`, and the metering usage route silently
dropped because `metering` was never exposed to the API Gateway module.
"""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_GATEWAY_TF = ROOT / "infrastructure/aws/modules/api-gateway/main.tf"
LAMBDA_TF = ROOT / "infrastructure/aws/modules/lambda/main.tf"
LAMBDA_OUTPUTS_TF = ROOT / "infrastructure/aws/modules/lambda/outputs.tf"
FRONTEND_API_DIR = ROOT / "frontend/src/api"

_ROUTE_RE = re.compile(r'"(GET|POST|PUT|PATCH|DELETE) (/[^"]*)"\s*=\s*"(\w+)"')


def _normalise(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}/]*\}", "{}", path)
    return path.rstrip("/") or "/"


def _terraform_routes() -> dict[tuple[str, str], str]:
    text = API_GATEWAY_TF.read_text()
    return {(m.group(1), _normalise(m.group(2))): m.group(3) for m in _ROUTE_RE.finditer(text)}


def _route_declared(routes: dict[tuple[str, str], str], method: str, path: str) -> bool:
    if (method, path) in routes:
        return True
    segments = path.split("/")
    for route_method, route_path in routes:
        candidate = route_path.split("/")
        if (
            route_method == method
            and len(candidate) == len(segments)
            and all(a == b or a == "{}" or b == "{}" for a, b in zip(candidate, segments, strict=True))
        ):
            return True
    return False


def _frontend_calls() -> dict[tuple[str, str], str]:
    """Every `{ method: 'X', path: '/v1/...' }` object literal in the API clients."""
    calls: dict[tuple[str, str], str] = {}
    for file in sorted(FRONTEND_API_DIR.glob("*.ts")):
        if file.name.endswith(".test.ts"):
            continue
        for block in re.finditer(r"\{[^{}]*?\}", file.read_text(), re.S):
            body = block.group(0)
            path = re.search(r"path:\s*[`'\"]([^`'\"]+)[`'\"]", body)
            if not path or "/v1/" not in path.group(1):
                continue
            method = re.search(r"method:\s*'(GET|POST|PUT|PATCH|DELETE)'", body)
            calls[(method.group(1) if method else "GET", _normalise(path.group(1)))] = file.name
    return calls


def _lambda_configs() -> dict[str, dict[str, str]]:
    """`key = { name = "...", handler = "pkg.handler.fn" }` entries in the lambda module's locals."""
    text = LAMBDA_TF.read_text()
    configs: dict[str, dict[str, str]] = {}
    section = None
    for line in text.splitlines():
        header = re.match(r"^\s{2}(\w+_configs|metering_config)\s*=\s*\{", line)
        if header:
            section = header.group(1)
            if section == "metering_config":
                handler = re.search(r'handler\s*=\s*"([^"]+)"', line)
                configs["metering"] = {"section": section, "handler": handler.group(1) if handler else ""}
            continue
        if section and re.match(r"^\s{2}\}", line):
            section = None
            continue
        entry = re.match(r'^\s{4}(\w+)\s*=\s*\{.*handler\s*=\s*"([^"]+)"', line)
        if section and entry:
            configs[entry.group(1)] = {"section": section, "handler": entry.group(2)}
    return configs


def _api_service_keys() -> set[str]:
    """Service keys the lambda module exposes to API Gateway (mirrors outputs.tf's api_lambda_arns)."""
    configs = _lambda_configs()
    keys = {k for k, v in configs.items() if v["section"] in ("vpc_api_configs", "non_vpc_api_configs")}
    keys |= set(re.findall(r'^\s+(\w+)\s*=\s*"arn:aws:lambda', LAMBDA_OUTPUTS_TF.read_text(), re.M))
    return keys


class TestApiGatewayRoutes:
    def test_every_frontend_api_call_is_routable(self):
        routes = _terraform_routes()
        assert routes, "no routes parsed from api-gateway/main.tf — the parser is broken"
        missing = sorted(
            f"{method} {path}  (called from frontend/src/api/{file})"
            for (method, path), file in _frontend_calls().items()
            if not _route_declared(routes, method, path)
        )
        assert not missing, (
            "Frontend calls these endpoints but API Gateway has no route for them "
            "(they work under scripts/local_server.py and 404 in AWS):\n  " + "\n  ".join(missing)
        )

    def test_every_route_targets_a_service_with_a_deployed_lambda(self):
        deployed = _api_service_keys()
        assert deployed, "no API Lambdas parsed from the lambda module — the parser is broken"
        orphaned = sorted(
            f"{method} {path} -> {service}" for (method, path), service in _terraform_routes().items() if service not in deployed
        )
        assert not orphaned, (
            "Routes point at a service key that isn't in the lambda module's api_lambda_arns, so "
            "api-gateway's `active_routes` filter silently drops them:\n  " + "\n  ".join(orphaned)
        )

    def test_route_keys_are_unique_per_method_and_path(self):
        seen: dict[tuple[str, str], str] = {}
        duplicates = []
        for match in _ROUTE_RE.finditer(API_GATEWAY_TF.read_text()):
            key = (match.group(1), match.group(2))
            if key in seen:
                duplicates.append(f"{match.group(1)} {match.group(2)}")
            seen[key] = match.group(3)
        assert not duplicates, f"Duplicate route keys: {duplicates}"


class TestLambdaHandlers:
    @pytest.mark.parametrize("key", sorted(_lambda_configs()))
    def test_configured_handler_exists_in_the_service_module(self, key):
        handler = _lambda_configs()[key]["handler"]
        package, module, function = handler.split(".")
        source = ROOT / "services" / package / f"{module}.py"
        assert source.exists(), f"{key}: {source.relative_to(ROOT)} does not exist"
        defined = {node.name for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.FunctionDef)}
        assigned = {
            target.id
            for node in ast.walk(ast.parse(source.read_text()))
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert function in defined | assigned, (
            f"{key}: Terraform sets handler '{handler}' but {source.relative_to(ROOT)} defines no "
            f"'{function}' — every invocation would fail with Runtime.HandlerNotFound"
        )


CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github/workflows/_deploy-env.yml"


def _zip_layout(target: Path) -> None:
    """The tree CI zips for every Lambda: services/ flattened at the root, plus the `services` package."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "services", target, ignore=ignore, dirs_exist_ok=True)
    shutil.copytree(ROOT / "services", target / "services", ignore=ignore)
    shutil.copytree(ROOT / "shared", target / "shared", ignore=ignore)  # the shared layer, on the path in Lambda


class TestLambdaPackageLayout:
    """Lambda imports a handler as `tracking.handler`; that module imports `services.billing.service`. Both must
    resolve from the zip. With services/ only flattened, tracking, claims and excel failed with
    "No module named 'services'" (found 2026-11-19)."""

    def test_every_configured_handler_imports_in_the_zip_layout(self, tmp_path):
        _zip_layout(tmp_path)
        modules = sorted({config["handler"].rsplit(".", 1)[0] for config in _lambda_configs().values()})
        script = (
            "import importlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "bad = []\n"
            "for name in sys.argv[2:]:\n"
            "    try:\n"
            "        importlib.import_module(name)\n"
            "    except Exception as exc:\n"
            "        bad.append(f'{name}: {type(exc).__name__}: {exc}')\n"
            "print('\\n'.join(bad))\n"
            "sys.exit(1 if bad else 0)\n"
        )
        # -I: the repo root (and its `services` package) must not leak onto the path; the zip layout alone counts.
        result = subprocess.run(  # noqa: S603 - fixed argv: this interpreter, a test script, module names from Terraform
            [sys.executable, "-I", "-c", script, str(tmp_path), *modules], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, "Handlers that would not import in Lambda:\n" + result.stdout + result.stderr[-2000:]

    def test_ci_zips_carry_the_services_package(self):
        workflow = CI_WORKFLOW.read_text()
        flattened = re.findall(r"zip -r \.\./build/(\S+?)\.zip \. ", workflow)
        packaged = re.findall(r"zip -r build/(\S+?)\.zip services ", workflow)
        assert flattened, "no service zip step parsed from ci.yml — the parser is broken"
        assert flattened == packaged, f"every zip needs the `services` package too: {flattened} vs {packaged}"

    @pytest.mark.parametrize(
        "key", sorted(key for key, config in _lambda_configs().items() if config["handler"].startswith("scheduled."))
    )
    def test_every_scheduled_lambda_is_built_and_deployed(self, key):
        build_list = re.search(r"for job in ([^;]+); do", CI_WORKFLOW.read_text())
        assert build_list, "no scheduled-job build loop parsed from ci.yml — the parser is broken"
        assert key in build_list.group(1).split(), f"ci.yml builds no scheduled-{key}.zip, so its code is never shipped"
        assert re.search(rf'"[\w-]+:{key}"', DEPLOY_WORKFLOW.read_text()), f"_deploy-env.yml never deploys {key}"


EVENTBRIDGE_TF = ROOT / "infrastructure/aws/modules/eventbridge/main.tf"
BOOTSTRAP_LOCAL = ROOT / "scripts/bootstrap_local.sh"
_NOTIFICATION_QUEUES = ("sms", "whatsapp", "email")


class TestNoEventGoesToANotificationQueue:
    """Audit BE-09: the notification consumers read only what `shared/notifications.py` enqueues.

    A raw EventBridge event routed to their queues has no recipient and was skipped with a warning every time.
    Services enqueue notifications directly; the bus feeds the metering queue only.
    """

    def test_eventbridge_sends_to_the_metering_queue_only(self):
        text = EVENTBRIDGE_TF.read_text()
        targets = re.findall(r"sqs_queue_arns\[\s*\"(\w+)\"\s*\]", text)
        assert targets and set(targets) == {"metering"}
        assert 'eventbridge_queue_keys = ["metering"]' in text

    def test_no_rule_or_target_is_built_from_a_list_of_notification_routes(self):
        text = EVENTBRIDGE_TF.read_text()
        assert "routing_rules" not in text and "routing_sqs" not in text
        for queue in _NOTIFICATION_QUEUES:
            assert f'"{queue}"' not in text and f"sqs-{queue}" not in text

    def test_eventbridge_is_not_allowed_to_send_to_every_queue(self):
        # Least privilege: the delivery role and the queue policies cover the targeted queue, not all of them.
        text = EVENTBRIDGE_TF.read_text()
        assert "values(var.sqs_queue_arns)" not in text
        assert "for_each  = var.sqs_queue_urls" not in text

    def test_local_bootstrap_routes_no_events_to_notification_queues(self):
        text = BOOTSTRAP_LOCAL.read_text()
        assert "put-rule" in text  # the metering rule is still created
        for queue in _NOTIFICATION_QUEUES:
            assert f'logistics-{queue}"' not in text.split("EventBridge Rules", 1)[1].split("S3 Bucket", 1)[0]
        put_rules = re.findall(r'put-rule \\\s+--name "([\w-]+)"', text)
        assert put_rules == ["route-metering"]


class TestStorageSettingsReachTheCode:
    """The Lambdas were given `S3_BUCKET`, which nothing reads; `shared/providers` reads `S3_BUCKET_NAME` and fell back
    to "logistics-assets", which is not this deployment's bucket (2026-11-17)."""

    def test_the_lambda_environment_names_the_bucket_the_way_the_code_reads_it(self):
        providers = (ROOT / "shared/providers/__init__.py").read_text()
        assert 'os.environ.get("S3_BUCKET_NAME"' in providers
        assert re.search(r"^\s+S3_BUCKET_NAME\s+=\s+var\.bucket_name$", LAMBDA_TF.read_text(), re.M)

    def test_no_lambda_is_given_a_bucket_variable_nothing_reads(self):
        assert not re.search(r"^\s+S3_BUCKET\s+=", LAMBDA_TF.read_text(), re.M)


class TestFailureAlarmsMatchTheCounters:
    """Audit OPS-04: an alarm on an operation the code never counts, or under another namespace, never fires."""

    MONITORING = {
        "aws": ROOT / "infrastructure/aws/modules/monitoring",
        "azure": ROOT / "infrastructure/azure/modules/monitoring",
    }

    @pytest.mark.parametrize("cloud", ["aws", "azure"])
    def test_every_alarmed_operation_is_one_the_code_counts(self, cloud):
        from shared.observability import OPERATIONS

        text = (self.MONITORING[cloud] / "main.tf").read_text()
        alarmed = set(re.findall(r'operation\s*=\s*"(\w+)"', text)) | set(re.findall(r'Operation = "(\w+)"', text))
        alarmed |= {"notification_send"} if "notification_send" in text else set()
        assert {"invoice_generation", "audit_write", "notification_send"} <= alarmed
        assert alarmed <= OPERATIONS

    def test_the_aws_alarms_use_the_namespace_the_code_writes(self):
        from shared.observability import METRIC_NAMESPACE

        variables = (self.MONITORING["aws"] / "variables.tf").read_text()
        assert re.search(r'variable "metric_namespace" \{[^}]*default\s*=\s*"' + METRIC_NAMESPACE + '"', variables)
