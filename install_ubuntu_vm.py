#!/usr/bin/env python3

import subprocess
import sys
import os
import argparse
import time
import urllib.request

def run_command(cmd, check=True):
    """Execute shell command and return result"""
    try:
        if isinstance(cmd, list):
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True, check=check)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout, e.stderr

def check_vboxmanage():
    """Check if VBoxManage is installed and in PATH"""
    print("[1/7] Checking VirtualBox installation...")
    success, stdout, stderr = run_command("VBoxManage --version", check=False)

    if not success:
        print("ERROR: VBoxManage not found in PATH")
        print("Please install VirtualBox from: https://www.virtualbox.org/wiki/Downloads")
        print("\nOn Windows, ensure VirtualBox installation directory is in PATH:")
        print("  Typically: C:\\Program Files\\Oracle\\VirtualBox")
        sys.exit(1)

    version = stdout.strip()
    print(f"VirtualBox found: {version}")
    return True

def download_ubuntu_iso(iso_path):
    """Download Ubuntu 24.04 ISO if not present"""
    print("\n[2/7] Checking Ubuntu ISO...")

    if os.path.exists(iso_path):
        print(f"ISO already exists: {iso_path}")
        return iso_path

    print("Ubuntu 24.04 ISO not found.")
    print("\nPlease download Ubuntu 24.04 ISO manually from:")
    print("  https://ubuntu.com/download/server")
    print("  https://releases.ubuntu.com/24.04/")
    print(f"\nThen run this script again with: --iso-path <path-to-iso>")
    sys.exit(1)

def create_vm(vm_name, memory_mb, cpu_count, disk_size_mb):
    """Create a new VirtualBox VM"""
    print(f"\n[3/7] Creating VM: {vm_name}...")

    # Delete existing VM if it exists
    success, _, _ = run_command(f'VBoxManage showvminfo "{vm_name}"', check=False)
    if success:
        print(f"VM '{vm_name}' already exists. Removing it...")
        run_command(f'VBoxManage unregistervm "{vm_name}" --delete', check=False)
        time.sleep(2)

    # Create VM
    run_command([
        'VBoxManage', 'createvm',
        '--name', vm_name,
        '--ostype', 'Ubuntu_64',
        '--register'
    ])

    # Configure VM
    run_command([
        'VBoxManage', 'modifyvm', vm_name,
        '--memory', str(memory_mb),
        '--cpus', str(cpu_count),
        '--vram', '128',
        '--boot1', 'dvd',
        '--boot2', 'disk',
        '--boot3', 'none',
        '--boot4', 'none',
        '--audio', 'none',
        '--nic1', 'nat',
        '--natpf1', 'ssh,tcp,,2222,,22',
        '--natpf1', 'http,tcp,,8000,,80',
        '--natpf1', 'https,tcp,,8443,,443',
        '--natpf1', 'phpmyadmin,tcp,,8080,,8080'
    ])

    print(f"VM created with {memory_mb}MB RAM, {cpu_count} CPUs")

def create_storage(vm_name, disk_size_mb, iso_path):
    """Create and attach storage to VM"""
    print(f"\n[4/7] Creating storage...")

    # Get VM folder
    success, stdout, _ = run_command(f'VBoxManage showvminfo "{vm_name}" --machinereadable')
    vm_folder = None
    for line in stdout.split('\n'):
        if 'CfgFile=' in line:
            cfg_path = line.split('=')[1].strip('"')
            vm_folder = os.path.dirname(cfg_path)
            break

    if not vm_folder:
        print("ERROR: Could not determine VM folder")
        sys.exit(1)

    vdi_path = os.path.join(vm_folder, f"{vm_name}.vdi")

    # Create storage controller
    run_command([
        'VBoxManage', 'storagectl', vm_name,
        '--name', 'SATA',
        '--add', 'sata',
        '--controller', 'IntelAhci',
        '--portcount', '2',
        '--bootable', 'on'
    ])

    # Create virtual hard disk
    run_command([
        'VBoxManage', 'createmedium', 'disk',
        '--filename', vdi_path,
        '--size', str(disk_size_mb),
        '--format', 'VDI'
    ])

    # Attach hard disk
    run_command([
        'VBoxManage', 'storageattach', vm_name,
        '--storagectl', 'SATA',
        '--port', '0',
        '--device', '0',
        '--type', 'hdd',
        '--medium', vdi_path
    ])

    # Attach ISO
    run_command([
        'VBoxManage', 'storageattach', vm_name,
        '--storagectl', 'SATA',
        '--port', '1',
        '--device', '0',
        '--type', 'dvddrive',
        '--medium', iso_path
    ])

    print(f"Storage created: {disk_size_mb}MB disk")
    print(f"ISO attached: {iso_path}")

def enable_unattended_install(vm_name, iso_path, username, password, hostname):
    """Configure unattended installation"""
    print(f"\n[5/7] Configuring unattended installation...")

    cmd = [
        'VBoxManage', 'unattended', 'install', vm_name,
        '--iso', iso_path,
        '--user', username,
        '--password', password,
        '--full-user-name', username,
        '--hostname', hostname,
        '--install-additions',
        '--time-zone', 'UTC'
    ]

    success, stdout, stderr = run_command(cmd, check=False)

    if not success:
        print("WARNING: Unattended installation setup failed")
        print("You will need to install Ubuntu manually")
        print(f"Error: {stderr}")
        return False

    print(f"Unattended install configured (user: {username})")
    return True

def enable_autostart(vm_name):
    """Enable VM autostart on host boot"""
    print(f"\n[6/7] Enabling autostart on host boot...")

    run_command(['VBoxManage', 'modifyvm', vm_name, '--autostart-enabled', 'on'])
    run_command(['VBoxManage', 'modifyvm', vm_name, '--autostart-delay', '10'])

    print(f"VM autostart enabled (10 second delay)")

def start_vm(vm_name, headless=False):
    """Start the VM"""
    print(f"\n[7/7] Starting VM...")

    vm_type = 'headless' if headless else 'gui'
    run_command(['VBoxManage', 'startvm', vm_name, '--type', vm_type])

    if headless:
        print(f"VM started in headless mode")
    else:
        print(f"VM started with GUI")

def print_summary(vm_name, username, password, hostname, memory_mb, cpu_count, disk_size_gb, unattended):
    """Print installation summary"""
    print("\n" + "="*50)
    print("VM Creation Complete!")
    print("="*50)

    print(f"\nVM Name: {vm_name}")
    print(f"Hostname: {hostname}")
    print(f"Username: {username}")
    print(f"Password: {password}")

    print(f"\nResources:")
    print(f"  - RAM: {memory_mb}MB")
    print(f"  - CPUs: {cpu_count}")
    print(f"  - Disk: {disk_size_gb}GB")

    print(f"\nPort Forwarding (Host -> VM):")
    print(f"  - SSH:        localhost:2222  -> VM:22")
    print(f"  - HTTP:       localhost:8000  -> VM:80")
    print(f"  - HTTPS:      localhost:8443  -> VM:443")
    print(f"  - phpMyAdmin: localhost:8080  -> VM:8080")

    if unattended:
        print(f"\nInstallation Mode: Unattended (automatic)")
        print(f"  - The VM will install Ubuntu automatically")
        print(f"  - This may take 15-30 minutes")
        print(f"  - The VM will reboot when complete")
    else:
        print(f"\nInstallation Mode: Manual")
        print(f"  - Follow the Ubuntu installer prompts")
        print(f"  - Remember to eject the ISO after installation")

    print(f"\nAutostart:")
    print(f"  - VM will automatically start on host boot")
    print(f"  - Autostart delay: 10 seconds")

    print(f"\nAfter Installation:")
    print(f"  - SSH access: ssh -p 2222 {username}@localhost")
    print(f"  - Web access: http://localhost:8000")

    print(f"\nUseful Commands:")
    print(f'  VBoxManage startvm "{vm_name}" --type gui       # Start with display')
    print(f'  VBoxManage startvm "{vm_name}" --type headless  # Start without display')
    print(f'  VBoxManage controlvm "{vm_name}" poweroff       # Force shutdown')
    print(f'  VBoxManage controlvm "{vm_name}" acpipowerbutton # Graceful shutdown')
    print(f'  VBoxManage showvminfo "{vm_name}"               # Show VM info')
    print(f'  VBoxManage unregistervm "{vm_name}" --delete    # Delete VM')

    print("="*50)

def main():
    parser = argparse.ArgumentParser(description='Create Ubuntu 24.04 VM in VirtualBox')
    parser.add_argument('--vm-name', type=str, default='Ubuntu-24.04-Server',
                      help='VM name (default: Ubuntu-24.04-Server)')
    parser.add_argument('--iso-path', type=str, required=True,
                      help='Path to Ubuntu 24.04 ISO file')
    parser.add_argument('--memory', type=int, default=4096,
                      help='RAM in MB (default: 4096)')
    parser.add_argument('--cpus', type=int, default=2,
                      help='Number of CPUs (default: 2)')
    parser.add_argument('--disk-size', type=int, default=50,
                      help='Disk size in GB (default: 50)')
    parser.add_argument('--username', type=str, default='ubuntu',
                      help='Username for Ubuntu (default: ubuntu)')
    parser.add_argument('--password', type=str, default='ubuntu',
                      help='Password for Ubuntu (default: ubuntu)')
    parser.add_argument('--hostname', type=str, default='ubuntu-server',
                      help='Hostname (default: ubuntu-server)')
    parser.add_argument('--headless', action='store_true',
                      help='Start VM in headless mode (no GUI)')
    parser.add_argument('--no-start', action='store_true',
                      help='Do not start VM after creation')
    parser.add_argument('--manual-install', action='store_true',
                      help='Skip unattended installation setup')

    args = parser.parse_args()

    print("="*50)
    print("Ubuntu 24.04 VirtualBox VM Creator")
    print("="*50)
    print()

    # Check VirtualBox
    check_vboxmanage()

    # Check ISO
    iso_path = os.path.abspath(args.iso_path)
    download_ubuntu_iso(iso_path)

    # Create VM
    create_vm(args.vm_name, args.memory, args.cpus, args.disk_size * 1024)

    # Create storage
    create_storage(args.vm_name, args.disk_size * 1024, iso_path)

    # Configure unattended install
    unattended_success = False
    if not args.manual_install:
        unattended_success = enable_unattended_install(
            args.vm_name, iso_path, args.username, args.password, args.hostname
        )

    # Enable autostart
    enable_autostart(args.vm_name)

    # Start VM
    if not args.no_start:
        start_vm(args.vm_name, args.headless)
    else:
        print("\nVM created but not started (--no-start flag)")

    # Print summary
    print_summary(
        args.vm_name, args.username, args.password, args.hostname,
        args.memory, args.cpus, args.disk_size, unattended_success
    )

if __name__ == "__main__":
    main()
