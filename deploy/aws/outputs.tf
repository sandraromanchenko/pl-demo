output "app_public_ip" {
  description = "Public (Elastic) IP of the app host."
  value       = aws_eip.app.public_ip
}

output "frontend_url" {
  description = "Board games search UI."
  value       = "http://${aws_eip.app.public_ip}/"
}

output "backend_url" {
  description = "Backend API base."
  value       = "http://${aws_eip.app.public_ip}:8000"
}

output "pmm_url" {
  description = "PMM monitoring UI (admin / var.pmm_password)."
  value       = "https://${aws_eip.app.public_ip}:8443/"
}

output "data_public_ip" {
  description = "Public IP of the data host (SSH/ops)."
  value       = aws_eip.data.public_ip
}

output "models_public_ip" {
  description = "Public IP of the models host (SSH/ops)."
  value       = aws_eip.models.public_ip
}

output "private_ips" {
  description = "Auto-assigned private IPs used for cross-host wiring."
  value = {
    data   = aws_network_interface.data.private_ip
    models = aws_network_interface.models.private_ip
    app    = aws_network_interface.app.private_ip
  }
}

output "ssh" {
  description = "SSH commands (key pair: var.key_name)."
  value = {
    data   = "ssh ubuntu@${aws_eip.data.public_ip}"
    models = "ssh ubuntu@${aws_eip.models.public_ip}"
    app    = "ssh ubuntu@${aws_eip.app.public_ip}"
  }
}
