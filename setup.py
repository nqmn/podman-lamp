#!/usr/bin/env python3

import subprocess
import sys
import os
import argparse
import time

def run_command(cmd, check=True, shell=False):
    """Execute shell command and return result"""
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()
        result = subprocess.run(cmd, capture_output=True, text=True, shell=shell, check=check)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout, e.stderr

def check_root():
    """Check if script is running as root"""
    if os.geteuid() != 0:
        print("Please run as root or with sudo")
        sys.exit(1)

def check_install_podman():
    """Check if Podman is installed, install if not"""
    print("[1/6] Checking Podman installation...")
    success, stdout, _ = run_command("which podman", check=False)

    if not success:
        print("Podman not found. Installing Podman...")
        run_command("apt-get update")
        run_command("apt-get install -y podman")
        print("Podman installed successfully.")
    else:
        success, version, _ = run_command("podman --version")
        print(f"Podman is already installed ({version.strip()})")

def install_certbot(domain, email):
    """Install Certbot for Let's Encrypt if domain is provided"""
    if not domain:
        return email

    print("\n[2/6] Installing Certbot for Let's Encrypt...")
    success, _, _ = run_command("which certbot", check=False)

    if not success:
        run_command("apt-get update")
        run_command("apt-get install -y certbot")
        print("Certbot installed successfully.")
    else:
        print("Certbot is already installed")

    if not email:
        email = f"admin@{domain}"

    return email

def enable_podman_socket():
    """Enable Podman systemd socket"""
    print("\n[3/6] Enabling Podman systemd socket...")
    run_command("systemctl enable --now podman.socket")

def create_network(network_name):
    """Create Podman network"""
    print(f"\n[4/6] Creating Podman network...")
    success, _, _ = run_command(f"podman network exists {network_name}", check=False)

    if success:
        print(f"Network {network_name} already exists")
    else:
        run_command(f"podman network create {network_name}")
        print(f"Network {network_name} created")

def setup_mysql(network_name, mysql_container, mysql_user, mysql_password, mysql_root_password):
    """Setup MySQL container"""
    print(f"\n[5/6] Setting up MySQL container...")

    # Stop and remove existing container
    run_command(f"podman stop {mysql_container}", check=False)
    run_command(f"podman rm {mysql_container}", check=False)

    # Create MySQL container
    cmd = [
        "podman", "run", "-d",
        "--name", mysql_container,
        "--network", network_name,
        "-e", f"MYSQL_ROOT_PASSWORD={mysql_root_password}",
        "-e", f"MYSQL_USER={mysql_user}",
        "-e", f"MYSQL_PASSWORD={mysql_password}",
        "-e", "MYSQL_DATABASE=testdb",
        "-p", "3306:3306",
        "-v", "mysql_data:/var/lib/mysql",
        "docker.io/library/mysql:8.0"
    ]
    run_command(cmd)
    print(f"MySQL container created (user: {mysql_user}, password: {mysql_password})")

    # Generate systemd service
    os.makedirs("/etc/systemd/system", exist_ok=True)
    run_command(f"podman generate systemd --new --name {mysql_container} --files --restart-policy=always")
    run_command(f"mv container-{mysql_container}.service /etc/systemd/system/", shell=True)
    run_command("systemctl daemon-reload")
    run_command(f"systemctl enable container-{mysql_container}.service")
    print("MySQL auto-start enabled")

def obtain_ssl_certificate(domain, email, apache_container):
    """Obtain Let's Encrypt SSL certificate"""
    print(f"Obtaining Let's Encrypt certificate for {domain}...")
    print("Note: Ensure that your domain points to this server's IP address")

    # Stop Apache temporarily
    run_command(f"podman stop {apache_container}", check=False)

    # Obtain certificate
    cmd = [
        "certbot", "certonly", "--standalone",
        "--non-interactive",
        "--agree-tos",
        "--email", email,
        "-d", domain,
        "--preferred-challenges", "http"
    ]
    success, _, stderr = run_command(cmd, check=False)

    if not success:
        print("Certificate generation failed. You may need to configure DNS first.")
        return False

    # Copy certificates
    cert_path = f"/etc/letsencrypt/live/{domain}"
    if os.path.isdir(cert_path):
        run_command(f"cp {cert_path}/fullchain.pem /opt/apache-ssl/certs/", shell=True)
        run_command(f"cp {cert_path}/privkey.pem /opt/apache-ssl/certs/", shell=True)
        run_command("chmod 644 /opt/apache-ssl/certs/*.pem", shell=True)
        print(f"SSL certificate installed for {domain}")
        return True

    return False

def create_ssl_config(domain):
    """Create Apache SSL configuration"""
    ssl_config = f"""LoadModule ssl_module modules/mod_ssl.so
LoadModule socache_shmcb_module modules/mod_socache_shmcb.so

Listen 443

SSLCipherSuite HIGH:MEDIUM:!MD5:!RC4:!3DES
SSLProxyCipherSuite HIGH:MEDIUM:!MD5:!RC4:!3DES
SSLHonorCipherOrder on
SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
SSLProxyProtocol all -SSLv3 -TLSv1 -TLSv1.1
SSLPassPhraseDialog  builtin
SSLSessionCache        "shmcb:/usr/local/apache2/logs/ssl_scache(512000)"
SSLSessionCacheTimeout  300

<VirtualHost *:443>
    ServerName {domain}
    DocumentRoot /usr/local/apache2/htdocs

    SSLEngine on
    SSLCertificateFile /usr/local/apache2/conf/certs/fullchain.pem
    SSLCertificateKeyFile /usr/local/apache2/conf/certs/privkey.pem

    <Directory /usr/local/apache2/htdocs>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
"""
    with open("/opt/apache-ssl/ssl.conf", "w") as f:
        f.write(ssl_config)

def setup_apache(network_name, apache_container, domain, email):
    """Setup Apache2 container"""
    print(f"\n[6/6] Setting up Apache2 container...")

    # Stop and remove existing container
    run_command(f"podman stop {apache_container}", check=False)
    run_command(f"podman rm {apache_container}", check=False)

    # Create directories
    os.makedirs("/opt/apache-ssl/certs", exist_ok=True)
    os.makedirs("/opt/apache-ssl/www", exist_ok=True)

    has_ssl = False

    # Setup SSL if domain provided
    if domain:
        if obtain_ssl_certificate(domain, email, apache_container):
            create_ssl_config(domain)

            # Create Apache with SSL
            cmd = [
                "podman", "run", "-d",
                "--name", apache_container,
                "--network", network_name,
                "-p", "80:80",
                "-p", "443:443",
                "-v", "/opt/apache-ssl/www:/usr/local/apache2/htdocs:Z",
                "-v", "/opt/apache-ssl/certs:/usr/local/apache2/conf/certs:Z",
                "-v", "/opt/apache-ssl/ssl.conf:/usr/local/apache2/conf/extra/httpd-ssl.conf:Z",
                "docker.io/library/httpd:2.4",
                "sh", "-c", "echo 'Include conf/extra/httpd-ssl.conf' >> /usr/local/apache2/conf/httpd.conf && httpd-foreground"
            ]
            run_command(cmd)
            print("Apache2 container created with SSL support")
            has_ssl = True

            # Setup auto-renewal
            print("Setting up automatic certificate renewal...")
            renewal_cmd = f"0 3 * * * certbot renew --quiet --deploy-hook 'cp /etc/letsencrypt/live/{domain}/fullchain.pem /opt/apache-ssl/certs/ && cp /etc/letsencrypt/live/{domain}/privkey.pem /opt/apache-ssl/certs/ && podman restart {apache_container}'"

            # Get existing crontab
            success, current_cron, _ = run_command("crontab -l", check=False)
            if success:
                new_cron = current_cron + "\n" + renewal_cmd
            else:
                new_cron = renewal_cmd

            # Set new crontab
            process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_cron)
            print("Auto-renewal configured (daily check at 3 AM)")
        else:
            print("Certificate not found, creating Apache without SSL")

    # Create Apache without SSL if no domain or SSL failed
    if not has_ssl:
        cmd = [
            "podman", "run", "-d",
            "--name", apache_container,
            "--network", network_name,
            "-p", "80:80",
            "-p", "443:443",
            "-v", "/opt/apache-ssl/www:/usr/local/apache2/htdocs:Z",
            "docker.io/library/httpd:2.4"
        ]
        run_command(cmd)
        print("Apache2 container created (HTTP only)")
        if not domain:
            print(f"To enable SSL, run: sudo python3 {sys.argv[0]} --domain your-domain.com --email your-email@example.com")

    # Generate systemd service
    run_command(f"podman generate systemd --new --name {apache_container} --files --restart-policy=always")
    run_command(f"mv container-{apache_container}.service /etc/systemd/system/", shell=True)
    run_command("systemctl daemon-reload")
    run_command(f"systemctl enable container-{apache_container}.service")
    print("Apache2 auto-start enabled")

    return has_ssl

def setup_phpmyadmin(network_name, phpmyadmin_container, mysql_container, mysql_user, mysql_password):
    """Setup phpMyAdmin container"""
    print("\n[Bonus] Setting up phpMyAdmin container...")

    # Stop and remove existing container
    run_command(f"podman stop {phpmyadmin_container}", check=False)
    run_command(f"podman rm {phpmyadmin_container}", check=False)

    # Wait for MySQL to be ready
    print("Waiting for MySQL to be ready...")
    time.sleep(10)

    # Create phpMyAdmin container
    cmd = [
        "podman", "run", "-d",
        "--name", phpmyadmin_container,
        "--network", network_name,
        "-e", f"PMA_HOST={mysql_container}",
        "-p", "8080:80",
        "docker.io/phpmyadmin/phpmyadmin:latest"
    ]
    run_command(cmd)
    print("phpMyAdmin container created with login authentication")

    # Generate systemd service
    run_command(f"podman generate systemd --new --name {phpmyadmin_container} --files --restart-policy=always")
    run_command(f"mv container-{phpmyadmin_container}.service /etc/systemd/system/", shell=True)
    run_command("systemctl daemon-reload")
    run_command(f"systemctl enable container-{phpmyadmin_container}.service")
    print("phpMyAdmin auto-start enabled")

def setup_backup(mysql_container, mysql_root_password):
    """Setup automatic daily backups"""
    print("\n[Backup] Setting up automatic daily backups...")

    # Create backup directory
    backup_dir = "/opt/podman-backups"
    os.makedirs(backup_dir, exist_ok=True)

    # Create backup script
    backup_script = f"""#!/bin/bash
# Podman LAMP Stack Backup Script
BACKUP_DIR="{backup_dir}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/backup_$DATE"
RETENTION_DAYS=30

mkdir -p "$BACKUP_PATH"

# Backup MySQL database
echo "Backing up MySQL database..."
podman exec {mysql_container} mysqldump -u root -p{mysql_root_password} --all-databases > "$BACKUP_PATH/mysql_dump.sql" 2>/dev/null

# Backup Apache web files
echo "Backing up Apache web files..."
tar -czf "$BACKUP_PATH/apache_www.tar.gz" /opt/apache-ssl/www 2>/dev/null

# Backup SSL certificates if they exist
if [ -d "/opt/apache-ssl/certs" ]; then
    echo "Backing up SSL certificates..."
    tar -czf "$BACKUP_PATH/ssl_certs.tar.gz" /opt/apache-ssl/certs /etc/letsencrypt 2>/dev/null || true
fi

# Backup container configurations
echo "Backing up container configurations..."
podman inspect {mysql_container} > "$BACKUP_PATH/mysql_config.json" 2>/dev/null || true
podman inspect apache2_server > "$BACKUP_PATH/apache_config.json" 2>/dev/null || true
podman inspect phpmyadmin > "$BACKUP_PATH/phpmyadmin_config.json" 2>/dev/null || true

# Delete old backups
echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -type d -name "backup_*" -mtime +$RETENTION_DAYS -exec rm -rf {{}} \\; 2>/dev/null || true

echo "Backup completed: $BACKUP_PATH"
"""

    # Write backup script
    backup_script_path = "/usr/local/bin/podman-lamp-backup.sh"
    with open(backup_script_path, "w") as f:
        f.write(backup_script)

    # Make executable
    run_command(f"chmod +x {backup_script_path}")
    print(f"Backup script created: {backup_script_path}")

    # Add to crontab (daily at 2 AM)
    backup_cron = f"0 2 * * * {backup_script_path} >> /var/log/podman-backup.log 2>&1"

    # Get existing crontab
    success, current_cron, _ = run_command("crontab -l", check=False)
    if success:
        # Check if backup job already exists
        if "podman-lamp-backup.sh" not in current_cron:
            new_cron = current_cron + "\n" + backup_cron
        else:
            new_cron = current_cron
            print("Backup cron job already exists")
    else:
        new_cron = backup_cron

    # Set new crontab
    if "podman-lamp-backup.sh" not in (current_cron if success else ""):
        process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
        process.communicate(input=new_cron)
        print("Automatic backup configured (daily at 2 AM)")
        print(f"Backup directory: {backup_dir}")
        print("Backup retention: 30 days (1 month)")

    # Run initial backup
    print("Running initial backup...")
    run_command(backup_script_path, check=False)

def print_summary(domain, has_ssl, mysql_user, mysql_password, mysql_root_password):
    """Print installation summary"""
    print("\n" + "="*40)
    print("Installation Complete!")
    print("="*40)
    print("\nServices Status:")

    if has_ssl and domain:
        print(f"  - Apache2:    Running on https://{domain} (HTTP: port 80, HTTPS: port 443)")
    else:
        print("  - Apache2:    Running on http://localhost:80")

    print("  - MySQL:      Running on port 3306")
    print("  - phpMyAdmin: Running on http://localhost:8080")

    print("\nMySQL Credentials:")
    print(f"  - Username: {mysql_user}")
    print(f"  - Password: {mysql_password}")
    print(f"  - Root Password: {mysql_root_password}")

    if has_ssl and domain:
        print("\nSSL Certificate:")
        print(f"  - Domain: {domain}")
        print("  - Auto-renewal: Enabled (checks daily at 3 AM)")
        print("  - Certificate location: /opt/apache-ssl/certs/")

    print("\nWeb Root Directory: /opt/apache-ssl/www")
    print("All services are set to auto-start on boot")

    print("\nBackup Configuration:")
    print("  - Backup directory: /opt/podman-backups")
    print("  - Automatic backup: Every day at 2 AM")
    print("  - Retention period: 30 days (1 month)")
    print("  - Backup log: /var/log/podman-backup.log")

    print("\nUseful commands:")
    print("  - sudo podman ps                    # List running containers")
    print("  - sudo podman logs <container>      # View container logs")
    print("  - sudo systemctl status container-* # Check service status")
    print("  - sudo /usr/local/bin/podman-lamp-backup.sh  # Manual backup")
    print("  - sudo python3 setup_podman_stack.py --restore  # Restore latest backup")
    print("  - sudo ls -lh /opt/podman-backups   # View backups")

    if domain:
        print("  - sudo certbot renew --dry-run      # Test certificate renewal")
        print("  - sudo certbot certificates         # View certificate info")
        print("\nNote: Certbot renew runs automatically every day at 3 AM")

    print("="*40)

def restore_backup(backup_path=None):
    """Restore from backup"""
    print("\n" + "="*40)
    print("Podman LAMP Stack Restore")
    print("="*40)
    print()

    backup_dir = "/opt/podman-backups"

    # Find latest backup if no path specified
    if not backup_path:
        if not os.path.isdir(backup_dir):
            print(f"Error: Backup directory {backup_dir} not found")
            sys.exit(1)

        backups = sorted([d for d in os.listdir(backup_dir) if d.startswith("backup_")])
        if not backups:
            print(f"Error: No backups found in {backup_dir}")
            sys.exit(1)

        backup_path = os.path.join(backup_dir, backups[-1])
        print(f"Using latest backup: {backup_path}")
    else:
        if not os.path.isdir(backup_path):
            print(f"Error: Backup path {backup_path} not found")
            sys.exit(1)

    # Configuration
    MYSQL_CONTAINER = "mysql_server"
    APACHE_CONTAINER = "apache2_server"
    MYSQL_ROOT_PASSWORD = "1"

    print("\n[1/4] Stopping containers...")
    run_command(f"podman stop {MYSQL_CONTAINER}", check=False)
    run_command(f"podman stop {APACHE_CONTAINER}", check=False)
    time.sleep(3)

    # Restore MySQL
    mysql_dump = os.path.join(backup_path, "mysql_dump.sql")
    if os.path.isfile(mysql_dump):
        print("\n[2/4] Restoring MySQL database...")
        run_command(f"podman start {MYSQL_CONTAINER}", check=False)
        time.sleep(5)

        with open(mysql_dump, 'r') as f:
            process = subprocess.Popen(
                ['podman', 'exec', '-i', MYSQL_CONTAINER, 'mysql', '-u', 'root', f'-p{MYSQL_ROOT_PASSWORD}'],
                stdin=f,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate()
        print("MySQL database restored")
    else:
        print(f"\n[2/4] Warning: MySQL dump not found in {backup_path}")

    # Restore Apache files
    apache_backup = os.path.join(backup_path, "apache_www.tar.gz")
    if os.path.isfile(apache_backup):
        print("\n[3/4] Restoring Apache web files...")
        run_command(f"tar -xzf {apache_backup} -C /", shell=True)
        print("Apache web files restored")
    else:
        print(f"\n[3/4] Warning: Apache backup not found in {backup_path}")

    # Restore SSL certificates
    ssl_backup = os.path.join(backup_path, "ssl_certs.tar.gz")
    if os.path.isfile(ssl_backup):
        print("\n[4/4] Restoring SSL certificates...")
        run_command(f"tar -xzf {ssl_backup} -C /", shell=True)
        print("SSL certificates restored")
    else:
        print("\n[4/4] No SSL certificates to restore")

    # Restart containers
    print("\nRestarting containers...")
    run_command(f"podman restart {MYSQL_CONTAINER}")
    run_command(f"podman restart {APACHE_CONTAINER}")

    print("\n" + "="*40)
    print("Restore Complete!")
    print("="*40)
    print(f"\nRestored from: {backup_path}")
    print("\nAll services have been restarted")
    print("="*40)

def main():
    parser = argparse.ArgumentParser(description='Podman LAMP Stack Setup for Ubuntu 24.04')
    parser.add_argument('--domain', type=str, help='Domain name for Let\'s Encrypt SSL')
    parser.add_argument('--email', type=str, help='Email address for Let\'s Encrypt')
    parser.add_argument('--restore', nargs='?', const=True, metavar='BACKUP_PATH', help='Restore from backup (latest if no path specified)')
    args = parser.parse_args()

    # Check root first
    check_root()

    # Handle restore mode
    if args.restore is not None:
        if args.restore is True:
            restore_backup()
        else:
            restore_backup(args.restore)
        return

    print("="*40)
    print("Podman LAMP Stack Setup for Ubuntu 24.04")
    print("="*40)
    print()

    # Configuration
    NETWORK_NAME = "lamp_network"
    MYSQL_CONTAINER = "mysql_server"
    APACHE_CONTAINER = "apache2_server"
    PHPMYADMIN_CONTAINER = "phpmyadmin"
    MYSQL_USER = "user"
    MYSQL_PASSWORD = "1"
    MYSQL_ROOT_PASSWORD = "1"

    # Install components
    check_install_podman()
    email = install_certbot(args.domain, args.email)
    enable_podman_socket()
    create_network(NETWORK_NAME)
    setup_mysql(NETWORK_NAME, MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD)
    has_ssl = setup_apache(NETWORK_NAME, APACHE_CONTAINER, args.domain, email)
    setup_phpmyadmin(NETWORK_NAME, PHPMYADMIN_CONTAINER, MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD)
    setup_backup(MYSQL_CONTAINER, MYSQL_ROOT_PASSWORD)

    # Print summary
    print_summary(args.domain, has_ssl, MYSQL_USER, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD)

if __name__ == "__main__":
    main()
