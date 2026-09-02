variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-west-2"
}

variable "subnet_id" {
  description = "Existing shared subnet to launch into."
  type        = string
  default     = "subnet-058b6b3614187bbf1"
}

variable "ami" {
  description = "AMI id. Default is the approved Ubuntu 24.04 (noble) image in us-west-2."
  type        = string
  default     = "ami-096f5760b00bcd95c"
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH access (required; set in terraform.tfvars or TF_VAR_key_name)."
  type        = string
}

variable "ssh_key_path" {
  description = "Absolute path to the private key for key_name. Set it unless the key is in your ssh-agent; the aws_env output then adds `-i <path>` so demo/run.sh can connect. Use $HOME, not ~."
  type        = string
  default     = ""

  validation {
    condition     = var.ssh_key_path == "" || !startswith(var.ssh_key_path, "~")
    error_message = "ssh_key_path must be absolute: demo/run.sh word-splits DEMO_SSH_OPTS, so a leading ~ reaches ssh unexpanded."
  }
}

variable "web_ingress_cidr" {
  description = "CIDR allowed to reach the public web (frontend/backend/PMM UI) on the app host."
  type        = string
  default     = "0.0.0.0/0"
}

variable "billing_tag" {
  description = "Mandatory iit-billing-tag value."
  type        = string
  default     = "dev"
}

# Per-role instance types (models host larger for CPU embedding throughput).
variable "instance_type_data" {
  type    = string
  default = "t3.medium"
}

variable "instance_type_models" {
  type    = string
  default = "t3.xlarge"
}

variable "instance_type_app" {
  type    = string
  default = "t3.medium"
}

# Root disk sizes (GB).
variable "data_root_gb" {
  type    = number
  default = 50
}

variable "models_root_gb" {
  type    = number
  default = 40
}

variable "app_root_gb" {
  type    = number
  default = 30
}

variable "repo_url" {
  description = "Git URL of this repo (cloned on each host by user_data)."
  type        = string
  default     = "https://github.com/your-org/pl-demo.git"
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "mongot_image" {
  description = "mongot image WITH the OPENAI_COMPATIBLE provider (auto-embedding)."
  type        = string
  default     = "percona/percona-search-mongodb:1.70.4"
}

variable "embed_models" {
  description = "Embedding models to enable (comma-separated): drives Ollama pulls + vector indexes. Supported: bge-small,nomic-embed-text,bge-m3."
  type        = string
  default     = "bge-small"
}

variable "auto_start" {
  description = "If true, user_data starts data + models and seeds indexes so the UI is usable after boot. Default false keeps the presentation pre-demo state (images pulled, search not running)."
  type        = bool
  default     = false
}
