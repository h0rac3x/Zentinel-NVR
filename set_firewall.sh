#!/bin/bash

echo "Configuration of the firewall for Zentinel NVR..."

#  UFW
sudo ufw allow 80/tcp comment 'Zentinel Web Interface'
sudo ufw allow 22/tcp comment 'SSH Access'
sudo ufw deny 8000/tcp comment 'Block Django Direct Access'
sudo ufw deny 1984/tcp comment 'Block go2rtc Direct Access'

# active firewall (--force)
sudo ufw --force enable

# aurtomatic start on boot
sudo systemctl enable ufw

echo "Firewall updated and activate at the stard"
