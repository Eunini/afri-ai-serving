terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    oci    = { source = "oracle/oci", version = "~> 7.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
  backend "local" {}
}

# OCI authentication comes from ~/.oci/config, never from committed variables.
provider "oci" {
  region = var.region
}

variable "region" { type = string }
variable "compartment_ocid" { type = string }
variable "availability_domain" { type = string }
variable "ubuntu_arm_image_ocid" { type = string }
variable "ssh_public_key_path" { type = string }
variable "admin_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && !contains(["0.0.0.0/0", "0.0.0.0/1", "128.0.0.0/1"], var.admin_cidr)
    error_message = "Use a restricted administrator IPv4 CIDR."
  }
}
variable "node_count" {
  type    = number
  default = 1
  validation {
    condition     = contains([1, 2], var.node_count)
    error_message = "Use one server or one server plus one agent."
  }
}
variable "ocpus_per_node" {
  type    = number
  default = 2
}
variable "memory_gb_per_node" {
  type    = number
  default = 12
}
variable "credited_total_ocpus" {
  type    = number
  default = 2
}
variable "credited_total_memory_gb" {
  type    = number
  default = 12
}
variable "k3s_version" {
  type    = string
  default = "v1.33.5+k3s1"
}

resource "random_password" "join" {
  length  = 48
  special = false
}

resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.30.0.0/16"]
  display_name   = "afri-ai"
  dns_label      = "afriai"
}
resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
}
resource "oci_core_route_table" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.main.id
  }
}
resource "oci_core_security_list" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
  dynamic "ingress_security_rules" {
    for_each = toset([22, 6443])
    content {
      protocol = "6"
      source   = var.admin_cidr
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
  # HTTP is private to the administrator until a TLS ingress is configured.
  dynamic "ingress_security_rules" {
    for_each = toset([80, 443])
    content {
      protocol = "6"
      source   = var.admin_cidr
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
  ingress_security_rules {
    protocol = "all"
    source   = "10.30.0.0/16"
  }
}
resource "oci_core_subnet" "main" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.main.id
  cidr_block        = "10.30.1.0/24"
  route_table_id    = oci_core_route_table.main.id
  security_list_ids = [oci_core_security_list.main.id]
  dns_label         = "nodes"
}

locals {
  node_addresses = ["10.30.1.10", "10.30.1.11"]
}

resource "oci_core_instance" "node" {
  count               = var.node_count
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = "afri-ai-${count.index}"
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = var.ocpus_per_node
    memory_in_gbs = var.memory_gb_per_node
  }
  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_arm_image_ocid
    boot_volume_size_in_gbs = 50
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.main.id
    private_ip       = local.node_addresses[count.index]
    assign_public_ip = true
  }
  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      role       = count.index == 0 ? "server" : "agent"
      server     = local.node_addresses[0]
      version    = var.k3s_version
      token      = random_password.join.result
      node_ip    = local.node_addresses[count.index]
      admin_cidr = var.admin_cidr
    }))
  }
  lifecycle {
    precondition {
      condition     = var.node_count * var.ocpus_per_node <= var.credited_total_ocpus && var.node_count * var.memory_gb_per_node <= var.credited_total_memory_gb
      error_message = "Requested nodes exceed the declared free/credited quota. Verify tenancy quota before changing the limits."
    }
  }
}

output "public_ips" { value = oci_core_instance.node[*].public_ip }
output "private_ips" { value = oci_core_instance.node[*].private_ip }
