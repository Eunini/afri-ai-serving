#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
provider_name="${CLOUD:-aws}"
case "$provider_name" in
  aws) infra_dir="$repo_dir/infra/aws" ;;
  oci) infra_dir="$repo_dir/infra" ;;
  *) echo "CLOUD must be aws or oci" >&2; exit 2 ;;
esac
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/afri-ai-serving/$provider_name"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
export TF_DATA_DIR="$state_dir/terraform"
# State contains the k3s join secret. Keep it outside the project, with restricted permissions.
umask 077
terraform -chdir="$infra_dir" init -reconfigure -backend-config="path=$state_dir/terraform.tfstate"
terraform -chdir="$infra_dir" "${@:-plan}"
