#!/usr/bin/env bash
# Build a Lambda-compatible ZIP with all Python dependencies bundled.
# Terraform's archive_file only zips source files; this script creates a full
# deployment package that LocalStack (and CI/CD) can run directly.
#
# Output: infrastructure/aws/modules/lambda/.builds/package/ (source tree + deps)
#         infrastructure/aws/modules/lambda/.builds/services.zip (final ZIP)
#
# Usage: bash scripts/build_lambda_zip.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/infrastructure/aws/modules/lambda/.builds"
PKG_DIR="$BUILD_DIR/package"

echo "=== Building Lambda deployment package ==="
echo "Project root : $PROJECT_ROOT"
echo "Build dir    : $BUILD_DIR"

# 1. Clean and recreate the package directory
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"

# 2. Install Python dependencies into the package root (Lambda expects them there)
echo ""
echo "--- Installing Python dependencies ---"
# Export the pinned runtime deps from the uv lock, then install for the arm64
# Lambda target (python3.13 runtime → manylinux_2_28).
uv export --frozen --no-hashes --no-emit-project --no-default-groups \
  --project "$PROJECT_ROOT" -o "$PROJECT_ROOT/build/runtime-reqs.txt"
uv pip install \
  --quiet \
  --target "$PKG_DIR" \
  --python-platform aarch64-manylinux_2_28 \
  --python-version 3.13 \
  --only-binary :all: \
  -r "$PROJECT_ROOT/build/runtime-reqs.txt"

# 3. Copy services/ and shared/ code (handler modules)
echo ""
echo "--- Copying source code ---"
cp -r "$PROJECT_ROOT/services/." "$PKG_DIR/"
# Also as the `services` package, so cross-service imports (`from services.billing …`) resolve; handlers stay at the
# root (`tracking.handler.lambda_handler`). Same layout as the CI zips.
cp -r "$PROJECT_ROOT/services" "$PKG_DIR/services"
cp -r "$PROJECT_ROOT/shared/."   "$PKG_DIR/shared/"

# 4. Remove unnecessary bloat from the ZIP
echo "--- Pruning bloat ---"
find "$PKG_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PKG_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$PKG_DIR" -type d -name "*.egg-info"  -exec rm -rf {} + 2>/dev/null || true
find "$PKG_DIR" -name "*.pyc" -delete 2>/dev/null || true

# 5. Create the ZIP — Terraform's archive_file will be skipped since the file exists
echo ""
echo "--- Creating ZIP ---"
mkdir -p "$BUILD_DIR"
(cd "$PKG_DIR" && zip -r "$BUILD_DIR/services.zip" . -x "*.pyc" -x "*/__pycache__/*" > /dev/null)

SIZE=$(du -sh "$BUILD_DIR/services.zip" | cut -f1)
echo ""
echo "=== Done: $BUILD_DIR/services.zip ($SIZE) ==="
