# Podman LAMP Stack Setup

Automated setup script for deploying a LAMP stack using Podman containers on Ubuntu 24.04.

## Server Requirements

- **Operating System**: Ubuntu 24.04 LTS
- **Privileges**: Root or sudo access
- **RAM**: Minimum 2GB recommended
- **Disk Space**: Minimum 10GB free space
- **Network**: Internet connection for downloading container images

## Installation

### Basic Setup (HTTP only)

```bash
sudo python3 setup_podman_stack.py
```

### Setup with SSL/HTTPS

```bash
sudo python3 setup_podman_stack.py --domain yourdomain.com --email your@email.com
```

**Note**: Ensure your domain DNS A record points to your server's IP address before running with SSL.

## Container Architecture

```
┌─────────────────────────────────────────────┐
│          Host System (Ubuntu 24.04)         │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │    Podman Network: lamp_network      │  │
│  │                                      │  │
│  │  ┌────────────────────────────────┐ │  │
│  │  │  Apache2 Container             │ │  │
│  │  │  - httpd:2.4                   │ │  │
│  │  │  - Ports: 80 (HTTP), 443 (HTTPS)│ │  │
│  │  │  - Volume: /opt/apache-ssl/www │ │  │
│  │  │  - SSL: /opt/apache-ssl/certs  │ │  │
│  │  └────────────────────────────────┘ │  │
│  │                                      │  │
│  │  ┌────────────────────────────────┐ │  │
│  │  │  MySQL Container               │ │  │
│  │  │  - mysql:8.0                   │ │  │
│  │  │  - Port: 3306                  │ │  │
│  │  │  - Volume: mysql_data          │ │  │
│  │  │  - Database: testdb            │ │  │
│  │  └────────────────────────────────┘ │  │
│  │                                      │  │
│  │  ┌────────────────────────────────┐ │  │
│  │  │  phpMyAdmin Container          │ │  │
│  │  │  - phpmyadmin:latest           │ │  │
│  │  │  - Port: 8080                  │ │  │
│  │  └────────────────────────────────┘ │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## Default Credentials

- **MySQL User**: `user`
- **MySQL Password**: `1`
- **MySQL Root Password**: `1`

## Features

- Automated Podman installation
- MySQL 8.0 database server
- Apache 2.4 web server
- phpMyAdmin interface (port 8080)
- Optional Let's Encrypt SSL certificates
- Systemd service integration (auto-start on boot)
- Automatic SSL certificate renewal
- Daily automated backups (2 AM)
- 30-day backup retention

## Web Root

Place your web files in: `/opt/apache-ssl/www`

## Backup & Restore

### Manual Backup
```bash
sudo /usr/local/bin/podman-lamp-backup.sh
```

### Restore Latest Backup
```bash
sudo python3 setup_podman_stack.py --restore
```

### Restore Specific Backup
```bash
sudo python3 setup_podman_stack.py --restore /opt/podman-backups/backup_20250108_120000
```

## Useful Commands

```bash
# List running containers
sudo podman ps

# View container logs
sudo podman logs apache2_server
sudo podman logs mysql_server

# Check service status
sudo systemctl status container-apache2_server
sudo systemctl status container-mysql_server

# Access MySQL shell
sudo podman exec -it mysql_server mysql -u root -p

# Test SSL renewal
sudo certbot renew --dry-run
```
