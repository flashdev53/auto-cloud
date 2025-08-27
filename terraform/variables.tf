variable "project"{
    type=string
    default="autocloud"
}
variable "location"{
    type=string
    default="centralindia"
}
variable "vm_size"{
    type=string
    default="Standard_B1s"
}
variable "admin_username"{
    type=string
    default="devcloud"
}
variable "ssh_public_key"{
    type=string
}
