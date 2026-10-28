terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
  backend "local" {}
}

variable "region" {
  type    = string
  default = "us-east-1"
}
variable "aws_profile" {
  type    = string
  default = "afri-research"
}
variable "aws_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the intended 12-digit AWS account ID."
  }
}
variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/afri-ai.pub"
}
variable "admin_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && !contains(["0.0.0.0/0", "0.0.0.0/1", "128.0.0.0/1"], var.admin_cidr)
    error_message = "Supply a restricted administrator IPv4 CIDR."
  }
}
variable "node_count" {
  type    = number
  default = 1
  validation {
    condition     = contains([1, 2], var.node_count)
    error_message = "Use one server or one server plus one worker."
  }
}
variable "instance_type" {
  type    = string
  default = "m7i-flex.large"
}
variable "k3s_version" {
  type    = string
  default = "v1.36.5+k3s1"
  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "Use an exact k3s release tag and its matching installer checksum."
  }
}
variable "k3s_installer_sha256" {
  type    = string
  default = "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad"
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.k3s_installer_sha256))
    error_message = "Supply the SHA256 of install.sh from the exact release tag."
  }
}
variable "research_lifetime_hours" {
  type        = number
  default     = 0
  description = "Zero for an operator-managed deployment; 1–24 for a bounded research run that terminates its instances on expiry."
  validation {
    condition     = var.research_lifetime_hours == 0 || (var.research_lifetime_hours >= 1 && var.research_lifetime_hours <= 24)
    error_message = "Choose zero, or a finite research lifetime from one to 24 hours."
  }
}
variable "project_name" {
  type    = string
  default = "afri-ai-research"
}

provider "aws" {
  region              = var.region
  profile             = var.aws_profile
  allowed_account_ids = [var.aws_account_id]
  default_tags { tags = { Project = var.project_name, ManagedBy = "terraform" } }
}
data "aws_availability_zones" "available" { state = "available" }
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
resource "random_password" "join" {
  length  = 48
  special = false
}
resource "aws_vpc" "main" {
  cidr_block           = "10.30.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.project_name }
}
resource "aws_internet_gateway" "main" { vpc_id = aws_vpc.main.id }
resource "aws_subnet" "main" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.30.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
}
resource "aws_route_table" "main" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table_association" "main" {
  subnet_id      = aws_subnet.main.id
  route_table_id = aws_route_table.main.id
}
resource "aws_security_group" "nodes" {
  name_prefix = "${var.project_name}-"
  vpc_id      = aws_vpc.main.id
  dynamic "ingress" {
    for_each = toset([22, 80, 443, 6443])
    content {
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = [var.admin_cidr]
    }
  }
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_key_pair" "nodes" {
  key_name_prefix = "${var.project_name}-"
  public_key      = file(pathexpand(var.ssh_public_key_path))
}
resource "aws_instance" "node" {
  count                                = var.node_count
  ami                                  = data.aws_ami.ubuntu.id
  instance_type                        = var.instance_type
  subnet_id                            = aws_subnet.main.id
  private_ip                           = "10.30.1.${10 + count.index}"
  vpc_security_group_ids               = [aws_security_group.nodes.id]
  key_name                             = aws_key_pair.nodes.key_name
  user_data_replace_on_change          = true
  instance_initiated_shutdown_behavior = var.research_lifetime_hours > 0 ? "terminate" : "stop"
  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    role             = count.index == 0 ? "server" : "agent"
    server           = "10.30.1.10"
    version          = var.k3s_version
    token            = random_password.join.result
    node_ip          = "10.30.1.${10 + count.index}"
    admin_cidr       = var.admin_cidr
    installer_sha256 = var.k3s_installer_sha256
    lifetime_seconds = ceil(var.research_lifetime_hours * 3600)
  })
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  tags       = { Name = "${var.project_name}-${count.index}" }
  depends_on = [aws_route_table_association.main]
}
output "public_ips" { value = aws_instance.node[*].public_ip }
output "private_ips" { value = aws_instance.node[*].private_ip }
output "instance_ids" { value = aws_instance.node[*].id }
