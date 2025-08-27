output "web_public_ip" {
  value = azurerm_public_ip.web_pip.ip_address
}

output "app_public_ip" {
  value = azurerm_public_ip.app_pip.ip_address
}

output "web_private_ip" {
  value = azurerm_network_interface.web_nic.ip_configuration[0].private_ip_address
}

output "app_private_ip" {
  value = azurerm_network_interface.app_nic.ip_configuration[0].private_ip_address
}
