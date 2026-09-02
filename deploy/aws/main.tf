terraform {
  required_version = ">= 1.3.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---- Shared subnet ----------------------------------------------------------
data "aws_subnet" "shared" {
  id = var.subnet_id
}

# ---- Security group ---------------------------------------------------------
# Attached to all three hosts: SSH, ICMP, all traffic within the SG (private
# cross-host ports), egress all, plus the public web ports (served by app host).
resource "aws_security_group" "pl_demo" {
  name        = "pl-demo"
  description = "pl-demo board games search"
  vpc_id      = data.aws_subnet.shared.vpc_id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "ICMP"
    from_port   = 8
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "all traffic within this SG (cross-host)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }
  ingress {
    description = "frontend"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.web_ingress_cidr]
  }
  ingress {
    description = "backend API"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.web_ingress_cidr]
  }
  ingress {
    description = "PMM UI"
    from_port   = 8443
    to_port     = 8443
    protocol    = "tcp"
    cidr_blocks = [var.web_ingress_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name              = "pl-demo"
    "iit-billing-tag" = var.billing_tag
  }
}

# ---- ENIs: pre-created so each host's user_data can reference the others'
# auto-assigned private IPs without a Terraform dependency cycle. -------------
resource "aws_network_interface" "data" {
  subnet_id       = var.subnet_id
  security_groups = [aws_security_group.pl_demo.id]
  tags            = { Name = "pl-demo-data", "iit-billing-tag" = var.billing_tag }
}

resource "aws_network_interface" "models" {
  subnet_id       = var.subnet_id
  security_groups = [aws_security_group.pl_demo.id]
  tags            = { Name = "pl-demo-models", "iit-billing-tag" = var.billing_tag }
}

resource "aws_network_interface" "app" {
  subnet_id       = var.subnet_id
  security_groups = [aws_security_group.pl_demo.id]
  tags            = { Name = "pl-demo-app", "iit-billing-tag" = var.billing_tag }
}

# ---- EIPs: public reachability (SSH/egress for all; web on app) -------------
# Allocated without an attachment so the app host's public IP is known before
# its user_data is rendered. Association is a separate resource below, because
# AssociateAddress rejects an ENI whose instance is still pending-instance-
# creation, and the allocation cannot depend on the instance without a cycle.
resource "aws_eip" "data" {
  domain = "vpc"
  tags   = { Name = "pl-demo-data", "iit-billing-tag" = var.billing_tag }
}

resource "aws_eip" "models" {
  domain = "vpc"
  tags   = { Name = "pl-demo-models", "iit-billing-tag" = var.billing_tag }
}

resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "pl-demo-app", "iit-billing-tag" = var.billing_tag }
}

# ---- Per-role .env contents (cross-host endpoints resolved from ENI IPs) -----
locals {
  pmm_port = 8443

  data_env = <<-EOT
    MONGOT_IMAGE=${var.mongot_image}
    TEI_URL=http://${aws_network_interface.models.private_ip}:8085
    OLLAMA_URL=http://${aws_network_interface.models.private_ip}:11434
    PMM_SERVER=${aws_network_interface.app.private_ip}
    PMM_SERVER_PORT=${local.pmm_port}
    PMM_USERNAME=admin
    PMM_PASSWORD=admin1
    MONGO_HOST=mongod
    MONGO_ADMIN_USER=root
    MONGO_ADMIN_PASSWORD=root
  EOT

  models_env = <<-EOT
    TEI_MODEL_ID=BAAI/bge-small-en-v1.5
    EMBED_MODELS=${var.embed_models}
  EOT

  app_env = <<-EOT
    MONGO_URI=mongodb://root:root@${aws_network_interface.data.private_ip}:27017/?authSource=admin&directConnection=true
    MONGO_DB=boardgames
    MONGO_COLLECTION=games
    TEXT_INDEX=text_index
    EMBED_MODELS=${var.embed_models}
    VITE_API_BASE=http://${aws_eip.app.public_ip}:8000
    FRONTEND_PORT=80
    PMM_HTTP_PORT=${local.pmm_port}
    PMM_PASSWORD=admin1
    DATA_PRIVATE_IP=${aws_network_interface.data.private_ip}
    SEED_DATA=true
  EOT
}

# ------------------------------------------------------------------- instances
resource "aws_instance" "data" {
  ami           = var.ami
  instance_type = var.instance_type_data
  key_name      = var.key_name

  network_interface {
    network_interface_id = aws_network_interface.data.id
    device_index         = 0
  }

  root_block_device {
    volume_size = var.data_root_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    role        = "data"
    env_content = local.data_env
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
    auto_start  = var.auto_start
  })

  tags = { Name = "pl-demo-data", "iit-billing-tag" = var.billing_tag }
}

resource "aws_instance" "models" {
  ami           = var.ami
  instance_type = var.instance_type_models
  key_name      = var.key_name

  network_interface {
    network_interface_id = aws_network_interface.models.id
    device_index         = 0
  }

  root_block_device {
    volume_size = var.models_root_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    role        = "models"
    env_content = local.models_env
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
    auto_start  = var.auto_start
  })

  tags = { Name = "pl-demo-models", "iit-billing-tag" = var.billing_tag }
}

resource "aws_instance" "app" {
  ami           = var.ami
  instance_type = var.instance_type_app
  key_name      = var.key_name

  network_interface {
    network_interface_id = aws_network_interface.app.id
    device_index         = 0
  }

  root_block_device {
    volume_size = var.app_root_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    role        = "app"
    env_content = local.app_env
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
    auto_start  = var.auto_start
  })

  tags = { Name = "pl-demo-app", "iit-billing-tag" = var.billing_tag }
}

# ---- EIP associations -------------------------------------------------------
# aws_instance creation blocks until the instance reaches `running`, so keying
# these off instance_id is what keeps AssociateAddress off a pending instance.
# allow_reassociation lets an apply converge when the address is already
# attached, e.g. state written before the allocation and association were split.
resource "aws_eip_association" "data" {
  allocation_id       = aws_eip.data.allocation_id
  instance_id         = aws_instance.data.id
  allow_reassociation = true
}

resource "aws_eip_association" "models" {
  allocation_id       = aws_eip.models.allocation_id
  instance_id         = aws_instance.models.id
  allow_reassociation = true
}

resource "aws_eip_association" "app" {
  allocation_id       = aws_eip.app.allocation_id
  instance_id         = aws_instance.app.id
  allow_reassociation = true
}
