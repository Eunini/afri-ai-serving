#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
infra_dir="$repo_dir/infra"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/afri-ai-serving/aws"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
export TF_DATA_DIR="$state_dir/terraform"
# State contains the k3s join secret. Keep it outside the project, with restricted permissions.
umask 077
terraform -chdir="$infra_dir" init -reconfigure -backend-config="path=$state_dir/terraform.tfstate"
terraform -chdir="$infra_dir" "${@:-plan}"
